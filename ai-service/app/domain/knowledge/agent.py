# -*- coding: utf-8 -*-
from __future__ import annotations
import hashlib
import json
import logging
import re
from uuid import uuid4
from collections.abc import Callable
from typing import Any, Dict, List, Optional

from cachetools import TTLCache
from langchain.agents import create_agent
from langchain.agents.middleware.model_call_limit import ModelCallLimitMiddleware
from langchain.agents.middleware.tool_call_limit import ToolCallLimitMiddleware
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import AIMessageChunk
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.infrastructure.persistence.memory import remember_knowledge_entities
from app.infrastructure.llm.middleware import build_summarization_middleware
from app.prompts.prompts import KNOWLEDGE_AGENT_PROMPT, KNOWLEDGE_PROMPT
from app.application.assistant.state import KnowledgeAgentState
from app.domain.knowledge.skill_observability import extract_knowledge_skill_reads
from app.infrastructure.config import config
from app.infrastructure.retrieval.retriever import get_retriever

logger = logging.getLogger("ai-service.knowledge.agent")

# Retriever and web fallback both prefix every real context with one of these
# headers. Split on the generated boundary instead of blank lines, because a
# single product chunk can contain multiple blank-line-separated sections.
_EVALUATION_CONTEXT_HEADER_RE = re.compile(r"(?m)^\[(?:资料|网络资料)\d+\]\s*来源：")


@tool
async def search_knowledge(query: str, search_mode: str = "hybrid", use_rerank: bool = True) -> dict:
    """在**内部知识库**中检索护肤/成分/使用方法等专业知识。

    ## 何时调用（首选）

    绝大多数护肤知识类问题都用本工具：
    - 成分原理："烟酰胺的功效原理"
    - 搭配禁忌："烟酰胺和VC能一起用吗"
    - 使用方法："视黄醇怎么用"
    - 适用人群："油皮适合什么防晒"

    ## 何时不用（改用 search_web）

    - 时效性问题（含"最新""2026""最近""新品"等词）
    - 本店未收录的品牌/产品
    - 本工具返回内容明显和问题不相关时，你可以主动改调 search_web

    ## 兜底机制

    本工具内部有极端兜底：只在 Milvus **完全没找到** 结果（sources 为空 或
    top_score < 0.1）时才自动调用网络搜索补齐。这只覆盖"索引里根本没有"的
    极端情况，不覆盖"有结果但不相关"的情况——后者需要你主动改调 search_web。

    Args:
        query: 精炼后的检索关键词（不是原问题，去掉客套/指代/无关修饰）。
        search_mode: 检索模式，可选值：
            - "hybrid"（默认）：BM25 稀疏 + 稠密向量融合，通常召回质量最好
            - "dense"：仅稠密向量（语义相似度）
            - "bm25"：仅 BM25 稀疏（精确词命中）
            正常用默认 hybrid 即可。
        use_rerank: 是否开启 rerank 精排。默认 True。
    """
    # 校验 search_mode，避免弱模型传乱码进来把 Milvus 请求打爆
    mode = (search_mode or "hybrid").lower()
    if mode not in ("hybrid", "dense", "bm25", "sparse"):
        mode = "hybrid"
    logger.info(
        "search_knowledge: 开始检索 query=%r mode=%s use_rerank=%s",
        query, mode, use_rerank,
    )
    # Query planning is deterministic and schema-constrained.  The LLM sees
    # this tool signature, not raw Milvus field names or expressions.
    from app.domain.knowledge.query_planner import plan_knowledge_query
    plan, query_plan = plan_knowledge_query(
        query, top_k=5, search_mode=mode, use_rerank=bool(use_rerank),
    )
    output = get_retriever().retrieve(plan)

    sources = [
        {
            "doc_id": s.doc_id,
            "chunk_id": s.chunk_id,
            "chunk_index": s.chunk_index,
            "title": s.doc,
            "score": round(s.score, 3),
        }
        for s in output.sources
    ]
    knowledge_context = output.knowledge_context
    fallback_used = False

    # ── 相关性判断：rerank top_score < 0.5 视为"内部知识库无相关内容" ──
    # 为什么用 0.5：
    # - rerank 分数是相对排序分，不是绝对相关性
    # - 经验上 < 0.5 大概率是"矬子里拔将军"（召回的都不相关，rerank 只是挑相对最不相关的）
    # - 这种情况**不能**给 LLM，中等模型看到"有资料"会拿它 + 训练知识编答案
    # 触发兜底时：直接**用博查结果替换** knowledge_context，**丢弃**低分 Milvus 内容
    top_score = max((s.score for s in output.sources), default=0)
    need_extreme_fallback = (len(sources) == 0 or top_score < 0.5)

    logger.info(
        "search_knowledge: Milvus 检索完成 sources=%d top_score=%.3f "
        "need_extreme_fallback=%s (阈值: sources=0 或 top<0.5)",
        len(sources), top_score, need_extreme_fallback,
    )

    if need_extreme_fallback:
        try:
            from app.infrastructure.clients.mcp_client import bocha_search, build_bocha_context

            logger.info("search_knowledge: 触发兜底（Milvus 无有效结果）query=%r", query)
            bocha_result = await bocha_search(query, count=5)
            channel = bocha_result.get("channel", "unknown")
            if bocha_result["success"] and bocha_result["results"]:
                fallback_used = True
                web_context = build_bocha_context(bocha_result["results"])

                # 关键：用博查结果**替换** knowledge_context，丢弃低分 Milvus 内容
                # 如果保留低分 Milvus 结果，中等模型会拿它 + 训练知识编答案
                knowledge_context = (
                    "## 网络搜索结果（内部知识库无相关内容，已改用网络搜索。"
                    "此类信息来自网络搜索，仅供参考）\n" + web_context
                )

                # sources 也只保留博查，剔除 Milvus 低分源
                sources = [
                    {"title": r["title"], "score": 0, "source": "bocha"}
                    for r in bocha_result["results"]
                ]
                logger.info(
                    "search_knowledge: 兜底成功 channel=%s 用 %d 条网络资料替换 Milvus 低分内容",
                    channel, len(bocha_result["results"]),
                )
            else:
                # 博查也没结果 → 清空低质量 Milvus 内容 + 明确指令
                # 防止 LLM 拿低分资料 + 训练知识编造
                logger.warning(
                    "search_knowledge: 兜底未拿到结果 channel=%s error=%s",
                    channel, bocha_result.get("error"),
                )
                knowledge_context = (
                    "## 检索失败\n"
                    "内部知识库没有相关内容，网络搜索也未拿到结果。\n"
                    "**必须**告知用户「根据现有资料无法回答该问题」，"
                    "禁止凭训练知识编造答案。"
                )
                sources = []
        except Exception:
            logger.warning("search_knowledge: 兜底失败", exc_info=True)
            # 异常同样清空，防止 LLM 用低分内容编造
            knowledge_context = (
                "## 检索失败\n"
                "内部知识库检索到低相关内容，网络搜索兜底异常。\n"
                "**必须**告知用户「根据现有资料无法回答该问题」，"
                "禁止凭训练知识编造答案。"
            )
            sources = []
    else:
        logger.info(
            "search_knowledge: Milvus 有结果，不自动兜底（如内容和问题不相关，"
            "请 LLM 主动改调 search_web）"
        )

    logger.info(
        "search_knowledge: 完成 fallback_used=%s 最终 sources=%d context_len=%d",
        fallback_used, len(sources), len(knowledge_context),
    )

    return {
        "knowledge_context": knowledge_context,
        "sources": sources,
        "total_results": len(output.results),
        "search_mode": mode,
        "use_rerank": bool(use_rerank),
        "fallback_used": fallback_used,
        "query_plan": query_plan.model_dump(),
    }


def _extract_sources(messages: list) -> list:
    """从工具 ToolMessage 里抽取 sources。

    支持两个工具：
    - search_knowledge 返回 {"sources": [{"title", "score", "source"?}, ...]}
    - search_web 返回 {"sources": [{"title", "url", "site_name", "date"}, ...]}

    统一输出结构：{"title", "score" | 0, "source": "milvus" | "bocha", "url"?}
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

        # search_web 返回值里 sources 项没有 score，加一个 "source": "bocha" 标记
        is_web_result = ("channel" in data) or (data.get("total_results") is not None
                                                 and data.get("success") is not None)

        for s in data.get("sources") or []:
            if not isinstance(s, dict):
                continue
            src_type = s.get("source") or ("bocha" if is_web_result else "milvus")
            item = {
                "doc_id": s.get("doc_id"),
                "chunk_id": s.get("chunk_id"),
                "chunk_index": s.get("chunk_index"),
                "title": s.get("title"),
                "score": s.get("score", 0),
                "source": src_type,
            }
            if s.get("url"):
                item["url"] = s["url"]
            sources.append(item)
    return sources


def _extract_tool_calls(messages: list) -> list[dict[str, Any]]:
    """Build a stable trace containing Knowledge business tools only."""
    calls: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for message in messages or []:
        if getattr(message, "type", "") == "ai":
            for raw in getattr(message, "tool_calls", None) or []:
                if isinstance(raw, dict):
                    call_id = str(raw.get("id") or "")
                    name = str(raw.get("name") or "")
                    args = raw.get("args") or {}
                else:
                    call_id = str(getattr(raw, "id", "") or "")
                    name = str(getattr(raw, "name", "") or "")
                    args = getattr(raw, "args", {}) or {}
                if name != "search_knowledge":
                    continue
                item = {
                    "tool_call_id": call_id or None,
                    "tool_name": name,
                    "input_params": args if isinstance(args, dict) else {},
                    "output": {},
                    "status": "started",
                }
                calls.append(item)
                if call_id:
                    by_id[call_id] = item
            continue

        if getattr(message, "type", "") != "tool":
            continue
        call_id = str(getattr(message, "tool_call_id", "") or "")
        item = by_id.get(call_id)
        if item is None:
            if str(getattr(message, "name", "") or "") != "search_knowledge":
                continue
            item = {
                "tool_call_id": call_id or None,
                "tool_name": str(getattr(message, "name", "") or ""),
                "input_params": {},
                "output": {},
                "status": "started",
            }
            calls.append(item)
            if call_id:
                by_id[call_id] = item
        payload: dict[str, Any] = {}
        content = getattr(message, "content", "")
        if isinstance(content, str) and content:
            try:
                parsed = json.loads(content)
                payload = parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                payload = {}
        # Keep trace useful without duplicating raw RAG contexts into reports.
        item["output"] = {
            key: payload.get(key)
            for key in ("total_results", "search_mode", "use_rerank", "fallback_used", "success", "channel")
            if key in payload
        }
        status = str(getattr(message, "status", "") or "").lower()
        item["status"] = "failed" if status in {"error", "failed"} else "completed"
    return calls


def _extract_last_knowledge_context(messages: list) -> str:
    """从最后一次 search_knowledge ToolMessage 里提取 knowledge_context。

    用于生成后自评：让 LLM 对比 "答案 vs 参考资料"，判断答案是否只来自资料。
    """
    for m in reversed(messages or []):
        if getattr(m, "type", "") != "tool":
            continue
        content = getattr(m, "content", "")
        if not isinstance(content, str) or not content:
            continue
        try:
            data = json.loads(content)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(data, dict) and "knowledge_context" in data:
            return str(data.get("knowledge_context") or "")
    return ""


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
    """从用户问题里抽取候选知识实体。此处保留正则版本作为兜底，LLM 版本见 _extract_entities_with_llm。"""
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

    entities = list(dict.fromkeys(entities))[:max_entities]
    return entities


class EntityExtractionResult(BaseModel):
    """LLM 实体抽取的结构化输出。"""
    entities: List[str] = Field(default_factory=list, description="从用户问题中提取的实体列表，如成分名、产品名、功效名。纯指代/反问/无实体时返回空列表。")


_ENTITY_EXTRACT_PROMPT = """从用户的知识问答问题中提取关键实体（成分名、产品名、原料名、功效名等）。

规则：
1. 只提取本轮问题中明确提到的实体，不要从上下文推断
2. 当前问题应已由主路由改写为完整表达；不要从历史猜测未出现在本轮的问题实体
3. 保序去重，最多 5 个
4. 没有实体时返回空列表
5. 示例：
   - "烟酰胺和视黄醇能一起用吗" → ["烟酰胺", "视黄醇"]
   - "第二个的成分是什么" → []（指代，不提取）
   - "透明质酸的功效原理" → ["透明质酸"]
   - "熊果苷和VC哪个美白效果好" → ["熊果苷", "VC"]
   - "你好" → []"""


async def _extract_entities_with_llm(query: str, max_entities: int = 5) -> Optional[List[str]]:
    """用 LLM 抽取实体。失败返回 None 触发正则兜底。"""
    from app.infrastructure.llm.llm import get_llm
    llm = get_llm()
    if llm is None:
        return None

    try:
        structured = llm.with_structured_output(EntityExtractionResult, method="function_calling")
        result = await structured.ainvoke(
            [
                {"role": "system", "content": _ENTITY_EXTRACT_PROMPT},
                {"role": "user", "content": query},
            ],
            config={"tags": ["ai_internal"]},
        )
    except Exception:
        logger.warning("LLM entity extraction failed, fallback to regex", exc_info=True)
        return None

    if not isinstance(result, EntityExtractionResult):
        return None

    entities = list(dict.fromkeys(result.entities))[:max_entities]
    return entities if entities else None


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


# ── 生成后自评（反幻觉最后一道关）──────────────────────────────────────

_GROUNDING_CHECK_PROMPT = """你是宽松但明确的答案审核员。判断【回答】是否**主要**基于【参考资料】。

## 判断原则

**默认 grounded=true**，只有出现下列**明显幻觉信号**才判为 false：

1. 回答中出现具体的学术引用（如"《XX期刊》2022 综述"、"《Nature》2023 研究"），但参考资料里没有该出处
2. 回答中出现具体的临床数据/百分比（如"减少 42%"、"临床验证有效率 89%"），但参考资料里没有该数据
3. 回答中出现具体医生/机构建议（如"张医生指出"、"XX 医院推荐"），但参考资料里没有该人物/机构
4. 参考资料明确是"检索失败"提示（含"检索失败""无相关内容"字样），但回答却给出了具体专业内容而非兜底表述

## 什么**不算**幻觉（判 true）

- 回答引用了参考资料里出现过的产品名、品牌名、成分名
- 回答用不同措辞表达参考资料的内容
- 回答基于参考资料做合理的推断和补充建议（如"敏感肌需谨慎"这类常识性提醒）
- 回答标注了"以上信息来自网络搜索，仅供参考"（说明用户会自行判断）
- 回答里有 emoji、markdown 结构、条目化排版

## 输出格式

只输出 JSON：{"grounded": true 或 false, "reason": "一句话说明"}

**保守优先**：判断困难时倾向 grounded=true，宁可放过也不误杀。"""


async def _grounding_check(llm, question: str, answer: str, knowledge_context: str) -> tuple[bool, str]:
    """让 LLM 自评答案是否完全来自参考资料。

    Returns:
        (grounded, reason) —— grounded=False 表示存在幻觉。

    实现细节：
    - 用 with_structured_output 拿结构化结果，避免 JSON 解析异常
    - config={"tags": ["ai_internal"]}：这次调用是"评审"，不应作为 token 流吐给前端
    - 任何异常（LLM 挂 / JSON 解析失败）都返回 (True, "check_failed")，不阻塞主流程
      —— 宁可放过，也不能因为审核异常导致用户拿不到答案
    """
    if llm is None or not answer:
        return True, "no_llm_or_empty_answer"

    class GroundingResult(BaseModel):
        grounded: bool = Field(description="回答是否完全基于参考资料")
        reason: str = Field(default="", description="判断理由")

    # 参考资料太长会撑爆 context，截断到 4000 字符（足以判断幻觉信号）
    context_snippet = (knowledge_context or "")[:4000]
    check_input = (
        f"【用户问题】{question}\n\n"
        f"【参考资料】\n{context_snippet or '（无参考资料）'}\n\n"
        f"【回答】\n{answer}"
    )

    try:
        structured = llm.with_structured_output(GroundingResult, method="function_calling")
        result = await structured.ainvoke(
            [
                {"role": "system", "content": _GROUNDING_CHECK_PROMPT},
                {"role": "user", "content": check_input},
            ],
            config={"tags": ["ai_internal"]},
        )
        if isinstance(result, GroundingResult):
            return bool(result.grounded), result.reason
        return True, "unknown_result_type"
    except Exception as e:  # noqa: BLE001
        logger.warning("grounding_check 异常，放过: %s", e)
        return True, f"check_error: {e}"


# 自评失败时的固定改写文案
_UNGROUNDED_FALLBACK_ANSWER = (
    "根据现有资料，我暂时无法回答该问题。为了避免给您误导，"
    "建议您咨询专业人士或参考权威医学/护肤指南。"
)


class KnowledgeAgent:
    """Skill-driven knowledge agent with evidence-grounded retrieval.

    The main Intent Router owns cross-turn reference resolution.  This Agent
    receives a self-contained question and does not read historical entities or
    expose a second reference-resolution tool to its model loop.

    ## 独立 checkpointer
    每次调用传唯一 thread_id 避免内部 tool_call 消息污染下一次调用。

    ## 对话级缓存
    同一问题（hash 去重）直接返回缓存结果，避免重复 RAG。

    实例懒构造，直到首次调用时才创建底层 agent。
    """

    def __init__(self, llm):
        self._llm = llm
        self._legacy_agent = None

    def _get_legacy_agent(self):
        """Return the explicit rollback runtime used when the switch is off."""
        if self._legacy_agent is None:
            # 工具集（简化设计）：
            # - search_knowledge：内部知识库 RAG。**内部自动兜底**：
            #   分数 < 0.5 时程序自动触发博查网络搜索，LLM 无感知。
            #   为什么不给 LLM search_web 独立工具：中等模型有"偷懒"倾向，
            #   拿到不相关的 Milvus 结果会用训练知识编答案，而不是主动改调 search_web。
            #   干脆把决策权从 LLM 手里拿走，全靠程序判断阈值。
            #
            # ToolCallLimit(search_knowledge, 2, continue)：
            #   超限后注入错误 ToolMessage，让模型用已有内容答（不硬停）
            # ModelCallLimit(5) 硬顶兜底，防弱模型死循环；recursion_limit 再兜一层
            #
            self._legacy_agent = create_agent(
                model=self._llm,
                checkpointer=_knowledge_checkpointer,
                system_prompt=KNOWLEDGE_PROMPT,
                tools=[search_knowledge],
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
        return self._legacy_agent

    async def run(
        self,
        *,
        messages: list,
        conversation_id: str = "",
        user_id: Optional[int | str] = None,
        token_sink: Callable[[str], None] | None = None,
    ) -> dict:
        """执行知识问答。

        Args:
            messages: 路由后当前问题的消息列表；不包含完整对话历史。
            conversation_id: 会话 ID，用于对话级缓存和实体写回。
            user_id: 用户 ID（可选），用于实体写回时的会话隔离。

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

        knowledge_runtime = (
            "deep_agent" if config.KNOWLEDGE_DEEP_AGENT_ENABLED
            else "langchain_agent"
        )

        # 对话级缓存：同一运行时 + 同一对话 + 同一问题，直接返回缓存。
        # 把运行时加入 key，确保人工回滚开关切换后不会复用另一条链的观测结果。
        cache_key = (
            f"{knowledge_runtime}:{conversation_id}:"
            f"{hashlib.md5(question.encode()).hexdigest()}"
        ) if question else ""
        if cache_key and cache_key in _knowledge_cache:
            cached = _knowledge_cache[cache_key]
            await self._persist_entities(conversation_id, user_id, question, cached.get("sources") or [])
            if token_sink is not None:
                for chunk in _stream_text_chunks(str(cached.get("answer") or "")):
                    token_sink(chunk)
            return cached

        # 每次调用使用唯一 thread_id，确保不受内部 tool_call 消息污染。
        # recursion_limit=12：单个检索工具的受控 Agent loop。
        # ModelCallLimit(run_limit=5, exit_behavior="end") 兜底防真死循环。
        # 观测：正常单轮问答 5-6 步，跨轮指代 8-10 步，20 有充裕余量。
        agent_input = {
            "messages": messages,
            "conversation_id": conversation_id,
            "user_id": user_id,
        }
        agent_config = {
            "configurable": {"thread_id": str(uuid4())},
            "recursion_limit": 32 if knowledge_runtime == "deep_agent" else 12,
        }
        skill_source = "/skills/knowledge-agent/"
        if config.KNOWLEDGE_DEEP_AGENT_ENABLED:
            from app.domain.knowledge.deep_agent import KnowledgeDeepAgentAdapter

            deep_runtime = KnowledgeDeepAgentAdapter(
                llm=self._llm,
                tools=[search_knowledge],
                checkpointer=_knowledge_checkpointer,
                skills_root=config.KNOWLEDGE_SKILLS_ROOT,
            ).build(system_prompt=KNOWLEDGE_AGENT_PROMPT)
            agent = deep_runtime.graph
            skill_source = deep_runtime.skill_source
        else:
            agent = self._get_legacy_agent()

        if token_sink is None:
            result = await agent.ainvoke(agent_input, config=agent_config)
        else:
            result = {}
            async for mode, payload in agent.astream(
                agent_input,
                config=agent_config,
                stream_mode=["values", "messages"],
            ):
                if mode == "values" and isinstance(payload, dict):
                    result = payload
                elif mode == "messages":
                    message, _metadata = payload
                    if isinstance(message, AIMessageChunk):
                        content = _stream_text_content(message.content)
                        if content:
                            token_sink(content)

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
        tool_calls = _extract_tool_calls(result_messages)
        skill_reads = (
            extract_knowledge_skill_reads(
                result_messages,
                skill_source=skill_source,
            )
            if knowledge_runtime == "deep_agent"
            else []
        )

        if not any(call.get("status") == "completed" for call in tool_calls):
            logger.warning("knowledge agent completed without a successful knowledge tool call")
            return {
                "answer": "我需要先检索可靠资料，但这次检索没有成功，请稍后再试。",
                "sources": [],
                "retrieved_contexts": [],
                "tool_calls": tool_calls,
                "confidence": 0.0,
                "has_answer": False,
                "task_type": "knowledge",
                "knowledge_runtime": knowledge_runtime,
                "skill_reads": skill_reads,
                "error": True,
                "error_code": "AI_RAG_TOOL_NOT_EXECUTED",
            }

        # ── 生成后自评（反幻觉最后一道关）──
        # 让 LLM 自己判断答案是否完全来自参考资料。判为 false 时改写为兜底文案。
        # 观察：中等模型自评通过率约 70%，能拦下大部分显性幻觉（虚构引用/数据）。
        # 自评异常时（LLM 挂 / JSON 失败）放过原答案，避免因审核环节导致用户拿不到答案。
        grounding_context = _extract_last_knowledge_context(result_messages)
        grounded, grounding_reason = await _grounding_check(
            self._llm, question, answer, grounding_context,
        )
        if not grounded:
            logger.warning(
                "knowledge: 自评未通过 → 改写答案为兜底文案. question=%r reason=%s "
                "原答案前 200 字: %s",
                question, grounding_reason, answer[:200],
            )
            answer = _UNGROUNDED_FALLBACK_ANSWER
        else:
            logger.info("knowledge: 自评通过 reason=%s", grounding_reason)

        # 抽取本轮候选实体并写回 Store，供下一轮主路由绑定。
        await self._persist_entities(conversation_id, user_id, question, sources)

        output = {
            "answer": answer or "知识检索暂时不可用，请稍后再试。",
            "sources": sources,
            # Only retained by the in-process graph result for offline RAGAS.
            # API response adaptation deliberately does not expose raw chunks to
            # H5/Java callers, preventing a much larger user-facing payload.
            "retrieved_contexts": self._split_evaluation_contexts(grounding_context) if sources else [],
            "tool_calls": tool_calls,
            "confidence": 0.7 if sources else 0.3,
            "has_answer": bool(sources) and grounded,
            "task_type": "knowledge",
            "knowledge_runtime": knowledge_runtime,
            "skill_reads": skill_reads,
        }

        # 存入缓存
        if cache_key:
            _knowledge_cache[cache_key] = output

        return output

    @staticmethod
    def _split_evaluation_contexts(knowledge_context: str) -> list[str]:
        """Keep bounded retrieval chunks for offline quality evaluation only.

        The retriever formats each real chunk with a stable ``[资料N] 来源：``
        header. Split on that generated boundary rather than on blank lines;
        blank lines are also valid inside one product/FAQ/review chunk.
        """
        text = (knowledge_context or "").strip()
        if not text:
            return []

        headers = list(_EVALUATION_CONTEXT_HEADER_RE.finditer(text))
        if not headers:
            # Keep non-Milvus/fallback text as one context instead of inventing
            # boundaries from its prose formatting.
            return [text[:4000]]

        contexts: list[str] = []
        for index, header in enumerate(headers):
            end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
            part = text[header.start():end].strip()
            if part:
                contexts.append(part[:4000])
        return contexts[:10]

    async def _persist_entities(
        self,
        conversation_id: str,
        user_id: Optional[int | str],
        question: str,
        sources: List[Dict[str, Any]],
    ) -> None:
        """从当前 question + sources 抽取候选实体，写回 Store。

        query 抽取优先，sources 抽取兜底（覆盖不到时补充）。
        写入失败不阻塞主流程 —— 记忆缺失最多让下一轮主路由无法绑定历史实体。
        """
        try:
            # LLM 优先，正则兜底
            entities = await _extract_entities_with_llm(question)
            if entities is None:
                entities = _extract_entities_from_query(question)
            if not entities:
                entities = _extract_entities_from_sources(sources)
            if entities:
                await remember_knowledge_entities(conversation_id, user_id, entities)
        except Exception:  # noqa: BLE001
            logger.warning("knowledge: 实体持久化失败", exc_info=True)


def _stream_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def _stream_text_chunks(text: str) -> list[str]:
    value = str(text or "")
    return [value[index:index + 6] for index in range(0, len(value), 6)]
