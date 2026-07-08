# -*- coding: utf-8 -*-
from __future__ import annotations
import hashlib
import json
import logging
import re
from uuid import uuid4
from typing import Any, Dict, List, Optional

from cachetools import TTLCache
from langchain.agents import create_agent
from langchain.agents.middleware.model_call_limit import ModelCallLimitMiddleware
from langchain.agents.middleware.tool_call_limit import ToolCallLimitMiddleware
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.tools import tool

from agents.memory import get_business_memory, remember_knowledge_entities
from agents.middleware import build_summarization_middleware
from agents.prompts import KNOWLEDGE_PROMPT
from agents.state import KnowledgeAgentState
from rag.models import RetrievalPlan
from rag.retriever import get_retriever
from tools.reference_tools import resolve_reference

logger = logging.getLogger("ai-service.knowledge.agent")


@tool
def search_knowledge(query: str, search_mode: str = "hybrid", use_rerank: bool = True) -> dict:
    """在知识库中检索与 query 相关的内容。返回检索到的知识片段和来源列表。

    使用时机：
    1. 收到用户知识类问题后，立即调用
    2. 把用户问题提炼为精准的检索查询词
    3. 如果一次检索不够，可以用不同的查询词再次检索

    Args:
        query: 精炼后的检索关键词（不是原问题，去掉客套/指代/无关修饰）。
        search_mode: 检索模式，可选值：
            - "hybrid"（默认）：BM25 稀疏 + 稠密向量融合，通常召回质量最好
            - "dense"：仅稠密向量（语义相似度），对同义改写、跨语言鲁棒
            - "bm25"：仅 BM25 稀疏（精确词命中），对专有名词/型号命中更好
            正常情况用默认 hybrid 即可，其他模式主要用于 A/B 对比测试。
        use_rerank: 是否开启 rerank 精排。默认 True（两阶段：hybrid 召回 20 → rerank 到 5）。
            关闭时直接返回 hybrid 前 5，主要用于性能对比。
    """
    # 校验 search_mode，避免弱模型传乱码进来把 Milvus 请求打爆
    mode = (search_mode or "hybrid").lower()
    if mode not in ("hybrid", "dense", "bm25", "sparse"):
        mode = "hybrid"
    plan = RetrievalPlan(query=query, top_k=5, search_mode=mode, use_rerank=bool(use_rerank))
    output = get_retriever().retrieve(plan)
    return {
        "knowledge_context": output.knowledge_context,
        "sources": [{"title": s.doc, "score": round(s.score, 3)} for s in output.sources],
        "total_results": len(output.results),
        "search_mode": mode,
        "use_rerank": bool(use_rerank),
    }


def _extract_sources(messages: list) -> list:
    """从 search_knowledge 工具的 ToolMessage 里抽取 sources。

    search_knowledge 返回 {"knowledge_context":..., "sources":[{"title","score"}], ...}，
    LangChain 把它 JSON 序列化进 ToolMessage.content，这里解析回来。
    去 ToolStrategy 后 sources 不再由结构化输出提供，改由这里抽取。
    """
    sources: list = []
    for m in messages or []:
        if getattr(m, "type", "") != "tool":
            continue
        content = getattr(m, "content", "")
        if not isinstance(content, str) or not content:
            continue
        try:
            data = json.loads(content)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(data, dict):
            continue
        for s in data.get("sources") or []:
            if isinstance(s, dict):
                sources.append({"title": s.get("title"), "score": s.get("score")})
    return sources


# ---- 知识实体抽取 ---------------------------------------------------------

# 停用词：把用户问题切成 tokens 后，这些不是实体主体，要过滤掉。
# 采用"最小可用"表：只收明显的功能词/疑问词，成分名/产品名不入表。
_ENTITY_STOPWORDS = frozenset({
    "和", "与", "还是", "或", "或者", "跟", "以及",
    "能", "能不能", "可以", "可不可以", "行不行", "行吗", "吗", "呢",
    "一起", "同时", "搭配", "组合", "使用", "用", "叠加", "混用",
    "有", "没", "是", "的", "了", "在", "把", "被",
    "什么", "怎么", "怎样", "为什么", "为啥", "如何",
    "成分", "功效", "作用", "效果", "副作用", "禁忌", "原理", "浓度", "机制",
    "推荐", "介绍", "对比", "比较", "区别", "选", "买",
    "我", "你", "他", "她", "它", "他们", "它们", "这个", "那个", "刚才",
    "适合", "适用", "针对", "对于", "关于",
    "分别", "都", "全部", "所有",
})

# 抽取 tokens 的正则：连续的中文/英文/数字段（单个字符至少长度 2 才算实体）
_ENTITY_TOKEN_PATTERN = re.compile(r"[一-龥A-Za-z0-9]{2,}")

# 分隔符：切分并列结构的信号词，如"和/与/或"—— 命中说明用户在并列提到多个实体
_ENTITY_SEPARATOR_PATTERN = re.compile(r"[和与跟、,，]|或(?:者)?|还是|以及")

# 停用词二次切分器：segment 里的连续汉字块（如"视黄醇能一起用吗"）需要用停用词
# 作为切点再切一次，否则整块被 _ENTITY_TOKEN_PATTERN 匹配成一个 token。
# 按长度倒序排列，让长停用词优先匹配（"能不能" 要先于 "能" 命中）。
_ENTITY_STOPWORD_SPLITTER = re.compile("|".join(sorted(_ENTITY_STOPWORDS, key=len, reverse=True)))


def _extract_entities_from_query(query: str, max_entities: int = 5) -> List[str]:
    """从用户问题里抽取候选知识实体。

    策略：
    1. 优先按分隔符（和/与/或/、）切分成 segments —— 覆盖并列结构
       如"烟酰胺和视黄醇能一起用吗" → segments = ["烟酰胺", "视黄醇能一起用吗"]
    2. 每个 segment 内部再按停用词二次切分 —— 中文连续块没空格，正则匹的是整块，
       如"视黄醇能一起用吗"必须切成 ["视黄醇", "能", "一起", "用吗"] 才能过滤掉后半段
    3. 取切分结果里第一个"看起来像实体"的 token（不在停用词表 + 长度 ≥ 2 + 非纯数字）
    4. 保序去重 + 截断

    这是"零成本"方案：纯正则，不调 LLM。够 90% case 用，覆盖不到的
    case（如复杂长句）由后续检索 sources 抽取兜底。
    """
    if not query:
        return []

    segments = _ENTITY_SEPARATOR_PATTERN.split(query) if _ENTITY_SEPARATOR_PATTERN.search(query) else [query]
    entities: list[str] = []

    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        entity = _pick_entity_from_segment(seg)
        if entity:
            entities.append(entity)

    # 保序去重
    entities = list(dict.fromkeys(entities))[:max_entities]
    return entities


def _pick_entity_from_segment(seg: str) -> Optional[str]:
    """从一个 segment（无分隔符的连续片段）里挑出主体实体。

    先按停用词二次切分：把"视黄醇能一起用吗"切成 ["视黄醇", "", "一起", "用吗"]
    然后逐个候选看是否满足实体条件（长度 ≥ 2 + 非纯数字 + 非停用词）。
    """
    # 二次切分：用停用词作为切点
    candidates = _ENTITY_STOPWORD_SPLITTER.split(seg)
    for cand in candidates:
        cand = cand.strip()
        if not cand or len(cand) < 2 or cand.isdigit() or cand in _ENTITY_STOPWORDS:
            continue
        # 再确认这个候选本身是一个合法 token（避免像 "。" 这类残留字符）
        m = _ENTITY_TOKEN_PATTERN.search(cand)
        if m:
            return m.group()
    return None


def _extract_entities_from_sources(sources: List[Dict[str, Any]], max_entities: int = 3) -> List[str]:
    """从检索到的 sources.title 里抽 backup 实体。

    query 抽取失败或结果太少时兜底：source title 通常包含核心实体名
    （如"烟酰胺搭配禁忌.md" → 烟酰胺）。这一步只补充、不覆盖。

    title 里的连续汉字块（如"烟酰胺搭配禁忌"）也需要按停用词二次切分，
    否则整块被当成一个 token。复用 _pick_entity_from_segment 保持逻辑一致。
    """
    out: list[str] = []
    for s in sources or []:
        title = (s.get("title") or "").strip()
        if not title:
            continue
        # 去扩展名和路径
        title = title.rsplit(".", 1)[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        entity = _pick_entity_from_segment(title)
        if entity and entity not in out:
            out.append(entity)
            if len(out) >= max_entities:
                return out
    return out


# KnowledgeAgent 专用独立 checkpointer，与主图 checkpointer 完全隔离
# 原因同 router：create_agent 内部的工具调用会往 checkpointer 写消息，
# 如果用共享 checkpointer + 同一 thread_id，tool_call 消息会混入下一轮
_knowledge_checkpointer = InMemorySaver()

# 对话级知识缓存：key = f"{conversation_id}:{md5(question)}"，value = run() 返回结果。
# 同一问题在同一会话中不必重复 RAG。
#
# 用 TTLCache 而非普通 dict：
#   - maxsize=1024：单进程最多 1024 条，超出 LRU 淘汰
#   - ttl=1800（30 分钟）：条目自动过期，避免长时间运行内存膨胀
# 多 worker 部署时每个 worker 有独立缓存，命中率分摊但不影响正确性。
# 如果未来需要跨进程共享，把这个 cache 挪到 PostgresStore 里即可。
_knowledge_cache: TTLCache = TTLCache(maxsize=1024, ttl=1800)


class KnowledgeAgent:
    """知识问答 agent：create_agent + search_knowledge + resolve_reference。

    ## 变更（2026-07-08）
    - 挂上 resolve_reference：支持"第二个的成分是什么"这类跨轮指代
      （通过 last_knowledge_entities 定位到上一轮谈过的成分/产品名）
    - 每次 run 时读 business_memory 并注入 prompt：LLM 能看到上轮实体
    - 检索完成后把候选实体写回 Store：下一轮就能被 resolve_reference 定位

    ## 独立 checkpointer
    每次调用传唯一 thread_id 避免内部 tool_call 消息污染下一次调用。

    ## 对话级缓存
    同一问题（hash 去重）直接返回缓存结果，避免重复 RAG。**但要注意**：
    命中缓存时也要更新 last_knowledge_entities，否则用户连问两次同样的问题、
    第三次追问"第二个"时会读到过期实体列表。

    实例懒构造，直到首次调用时才创建底层 agent。
    """

    def __init__(self, llm):
        self._llm = llm
        self._agent = None

    def _get_agent(self):
        if self._agent is None:
            # 去掉 response_format=ToolStrategy：原先是它和 ToolCallLimitMiddleware("end")
            # 打架导致 GraphRecursionError——ToolStrategy 注册的结构化输出工具也算"其他工具"，
            # 触发 tool_call_limit.py 的 NotImplementedError / jump_to:end 后
            # structured_response=None → 走错误分支"知识检索暂时不可用"。去掉后两者不再冲突。
            #
            # ToolCallLimit 改 continue：search_knowledge 最多 2 次，超限后注入错误
            # ToolMessage 提示模型"别再调了"，让模型用已检索内容组织回答（而非硬停）。
            # ModelCallLimit 作为硬顶兜底，防弱模型真的死循环；recursion_limit 再兜一层。
            #
            # state_schema=KnowledgeAgentState：让 resolve_reference 能通过
            # runtime.state 拿到 conversation_id / user_id 去读 Store。
            self._agent = create_agent(
                model=self._llm,
                checkpointer=_knowledge_checkpointer,
                system_prompt=KNOWLEDGE_PROMPT,
                tools=[search_knowledge, resolve_reference],
                state_schema=KnowledgeAgentState,
                middleware=[
                    build_summarization_middleware(),
                    ToolCallLimitMiddleware(
                        tool_name="search_knowledge",
                        run_limit=2,
                        exit_behavior="continue",
                    ),
                    ModelCallLimitMiddleware(run_limit=5, exit_behavior="end"),
                ],
            )
        return self._agent

    def _build_prompt_with_memory(self, memory: Dict[str, Any]) -> Optional[str]:
        """把知识实体记忆拼到 system_prompt 尾部，作为额外一条 SystemMessage。

        没有实体时返回 None，避免注入空段落。
        """
        entities: List[str] = memory.get("last_knowledge_entities") or []
        if not entities:
            return None
        lines = [f"  {i}. {e}" for i, e in enumerate(entities, 1)]
        return (
            "## 上一轮谈到的知识实体\n\n"
            + "\n".join(lines)
            + "\n\n如果本轮问题里含'第二个'、'它们'、'副作用/成分/怎么用'等指代，"
              "**必须先调 resolve_reference**，让它把指代解析到具体实体，"
              "再基于实体名做 search_knowledge。"
        )

    async def run(
        self,
        *,
        messages: list,
        conversation_id: str = "",
        user_id: Optional[int | str] = None,
    ) -> dict:
        """执行知识问答。

        Args:
            messages: 来自 supervisor 共享记忆的消息列表（含对话历史 + 当前问题）。
                      格式为 langchain_core.messages 对象列表。
            conversation_id: 会话 ID，用于业务记忆隔离 + 对话级缓存。
            user_id: 用户 ID（可选），传给工具用（当前 knowledge 没有用户维度工具，
                     但保留字段让 resolve_reference 未来接实体 → user_prefs 关联时用得上）。

        Returns:
            包含 answer、sources、confidence、task_type 等字段的字典。
        """
        if not messages:
            return {
                "answer": "没有收到任何问题。",
                "sources": [],
                "confidence": 0.0,
                "task_type": "knowledge",
                "error": True,
                "error_code": "AI_RAG_EMPTY_INPUT",
            }

        # 提取最后一条用户消息作为缓存 key 和实体抽取源
        question = ""
        for m in reversed(messages):
            mtype = getattr(m, "type", "")
            content = getattr(m, "content", "")
            if mtype == "human" and isinstance(content, str) and content.strip():
                question = content.strip()
                break

        # 读业务记忆，为本轮 prompt 注入 last_knowledge_entities
        try:
            memory = await get_business_memory(conversation_id, user_id)
        except Exception:  # noqa: BLE001
            logger.warning("knowledge: 读取 business_memory 失败，退化为无记忆模式", exc_info=True)
            memory = {}

        # 把上轮实体拼进 messages（作为一条 SystemMessage 追加在原 prompt 之后）。
        # 注意：create_agent 已经把 KNOWLEDGE_PROMPT 作为首条 SystemMessage 塞进去了，
        # 这里再追加一条 SystemMessage 让 LLM 看到"上一轮谈过什么"。
        memory_block = self._build_prompt_with_memory(memory)
        if memory_block:
            from langchain_core.messages import SystemMessage
            messages = [SystemMessage(content=memory_block), *messages]

        # 对话级缓存：同一对话 + 同一问题，直接返回缓存
        cache_key = f"{conversation_id}:{hashlib.md5(question.encode()).hexdigest()}" if question else ""
        if cache_key and cache_key in _knowledge_cache:
            cached = _knowledge_cache[cache_key]
            # 命中缓存也要更新实体记忆，避免过时（用户连问同样的问题两次时不会漏）
            await self._persist_entities(conversation_id, user_id, question, cached.get("sources") or [])
            return cached

        # 每次调用使用唯一 thread_id，确保不受内部 tool_call 消息污染。
        # recursion_limit=20：跨轮指代 case（resolve_reference → search_knowledge → 再答）
        # 需要 model+tool 各 3-4 次往返，加上 middleware 也算 step，12 步不够。
        # ModelCallLimit(run_limit=5, exit_behavior="end") 兜底防真死循环。
        # 观测：正常单轮问答 5-6 步，跨轮指代 8-10 步，20 有充裕余量。
        result = await self._get_agent().ainvoke(
            {
                "messages": messages,
                "conversation_id": conversation_id,
                "user_id": user_id,
            },
            config={
                "configurable": {"thread_id": str(uuid4())},
                "recursion_limit": 20,
            },
        )

        # answer 从最后一条 AI 消息 content 提取（纯文本，可流式）；
        # sources 从 search_knowledge 的 ToolMessage 里 JSON 解析抽取。
        result_messages = result.get("messages", [])
        answer = ""
        for m in reversed(result_messages):
            if getattr(m, "type", "") == "ai":
                content = getattr(m, "content", "")
                if isinstance(content, str) and content.strip():
                    answer = content
                    break
        sources = _extract_sources(result_messages)

        # 抽取本轮候选实体并写回 Store，供下一轮 resolve_reference 定位
        await self._persist_entities(conversation_id, user_id, question, sources)

        output = {
            "answer": answer or "知识检索暂时不可用，请稍后再试。",
            "sources": sources,
            "confidence": 0.7 if sources else 0.3,
            "has_answer": bool(sources),
            "task_type": "knowledge",
        }

        # 存入缓存
        if cache_key:
            _knowledge_cache[cache_key] = output

        return output

    async def _persist_entities(
        self,
        conversation_id: str,
        user_id: Optional[int | str],
        question: str,
        sources: List[Dict[str, Any]],
    ) -> None:
        """从当前 question + sources 抽取候选实体，写回 Store。

        query 抽取优先，sources 抽取兜底（覆盖不到时补充）。
        写入失败不阻塞主流程 —— 记忆缺失最多是下一轮 resolve_reference 失效。
        """
        try:
            entities = _extract_entities_from_query(question)
            if not entities:
                entities = _extract_entities_from_sources(sources)
            if entities:
                await remember_knowledge_entities(conversation_id, user_id, entities)
        except Exception:  # noqa: BLE001
            logger.warning("knowledge: 实体持久化失败", exc_info=True)
