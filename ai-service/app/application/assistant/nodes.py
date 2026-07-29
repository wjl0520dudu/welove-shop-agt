# -*- coding: utf-8 -*-
from __future__ import annotations
import json
import logging
from typing import Any, Callable, Dict, List, Optional
from langgraph.config import get_stream_writer
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from app.application.assistant.state import AssistantState
from app.infrastructure.persistence.memory import get_business_memory, remember_product_cards
from app.domain.shopping.preferences import build_preference_questions
from app.prompts.prompts import CHITCHAT_PROMPT
from app.infrastructure.errors import ErrorCode
from app.domain.shopping.agent import ShoppingAgent
from app.domain.knowledge.agent import KnowledgeAgent

logger = logging.getLogger("ai-service.nodes")

# 闲聊 agent 专用独立 checkpointer，与主图 checkpointer 完全隔离


# ---- 多模态 shopping 推荐话术 prompt --------------------------------
# 有图检索场景下，商品卡片已经通过 search_multimodal_v1 拿到，只需要 LLM
# 把这些卡片和用户 query 结合，写一段自然的推荐话术即可。
# 不走 tool loop，不需要 LLM 决定检索——只做「看图 + 看候选 + 写话术」。
_MULTIMODAL_SHOPPING_PROMPT = """你是电商导购。用户传了一张商品参考图并提出了需求，系统已经通过图文多模态检索找到了一批相似商品，你负责基于这些商品和用户意图写一段自然的推荐话术。

规则：
1. 直接推荐 top 3 商品，不要说"我为您找到了xxx"这种开场白，直接进入正题
2. 每款商品用 1-2 句话说明为什么它匹配用户的需求（价格、卖点、场景）
3. 结尾可以给一句选购建议（如"预算敏感选X，追求品质选Y"）
4. 不要虚构商品信息，只用给出的商品字段
5. 不要说"根据您上传的图片"这类废话，就当作正常推荐来写
6. 如果候选带有长期偏好匹配信息，可以据此解释推荐，但本轮用户明确要求优先

## 用户需求
{query_text}

## 检索到的候选商品（按相关度降序）
{product_list}

## 用户长期偏好（仅作软参考）
{preference_context}

## 你的推荐（100-200 字，Markdown 格式）
"""


def _format_products_for_prompt(cards: List[Dict[str, Any]], top_n: int = 5) -> str:
    """把 product_cards 列表格式化成 LLM 可读的 Markdown 文本。"""
    lines = []
    for i, c in enumerate(cards[:top_n], start=1):
        price = c.get("price") or c.get("base_price")
        line = (
            f"{i}. **{c.get('title', '')}**（品牌: {c.get('brand') or '未知'}, "
            f"价格: ¥{price}, 品类: {c.get('sub_category') or c.get('category') or '未知'}）"
        )
        desc = (c.get("description") or "").strip()
        if desc:
            line += f"\n   {desc[:120]}"
        matches = c.get("_personalization_matches") or []
        conflicts = c.get("_personalization_conflicts") or []
        if matches:
            line += f"\n   长期偏好匹配：{', '.join(matches[:3])}"
        if conflicts:
            line += f"\n   偏好冲突提醒：{', '.join(conflicts[:3])}"
        lines.append(line)
    return "\n".join(lines) if lines else "（无候选商品）"


async def _multimodal_shopping(
    llm,
    query_text: str,
    image_url: str,
    top_k: int = 5,
    business_memory: Optional[Dict[str, Any]] = None,
    token_sink: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """有图 shopping 分支：直接调 search_multimodal_v1，然后让 LLM 写推荐话术。

    不走 ShoppingAgent 的 tool loop，因为文本 LLM 看不到图，让它决定要不要
    调多模态工具没意义；直接程序侧调多模态检索，把结果交给 LLM 生成话术。
    """
    from app.domain.shopping.multimodal_search import (
        enforce_explicit_product_filters,
        extract_explicit_product_filters,
        search_multimodal_v1,
    )
    from app.domain.shopping.relevance_judge import filter_candidates
    from app.domain.shopping.personalization import personalized_rerank_candidates

    preferences = dict((business_memory or {}).get("user_preferences") or {})
    hard_filters = extract_explicit_product_filters(query_text)
    retrieval_counts: dict[str, int] = {}

    try:
        # 多召回一批候选，再允许 judge 过滤掉异类；最终仍只返回 top_k，
        # 不为了凑满 top_k 把明显不相关的商品补回来。
        retrieval_top_k = max(int(top_k or 5) * 2, int(top_k or 5))
        results = await search_multimodal_v1(
            query_text=query_text or "",
            query_image_url=image_url,
            top_k=retrieval_top_k,
            filters=hard_filters,
        )
        retrieval_counts["after_recall"] = len(results)
        results = await filter_candidates(
            llm=llm,
            query_text=query_text or "",
            query_image_url=image_url,
            candidates=results,
            limit=retrieval_top_k,
        )
        retrieval_counts["after_judge"] = len(results)
        results = personalized_rerank_candidates(results, preferences)[:top_k]
        retrieval_counts["after_personalization"] = len(results)
        results = enforce_explicit_product_filters(results, hard_filters)[:top_k]
        retrieval_counts["after_hard_filters"] = len(results)
    except Exception as e:  # noqa: BLE001
        logger.exception("multimodal shopping retrieval failed")
        return {
            "answer": "图片检索暂时不可用，请稍后再试。",
            "task_type": "shopping",
            "error": True,
            "error_code": ErrorCode.SHOPPING_ERROR,
            "message": str(e),
        }

    if not results:
        return {
            "answer": "抱歉，没有找到跟这张图相似的商品，可以换一张更清晰的图或者补充一下你的需求（预算、场景、品牌偏好）。",
            "task_type": "shopping",
            "product_cards": [],
            "sources": [],
            # Search was executed above even when every candidate is filtered
            # out. Preserve that fact for Contract evaluation and debugging.
            "tool_calls": [{
                "tool_name": "search_multimodal_v1",
                "input_params": {"query_text": query_text, "query_image_url": image_url, "top_k": top_k, "hard_filters": hard_filters, "retrieval_counts": retrieval_counts},
                "status": "completed_empty",
                "name": "search_multimodal_v1",
                "args": {"query_text": query_text, "query_image_url": image_url, "top_k": top_k, "hard_filters": hard_filters, "retrieval_counts": retrieval_counts},
            }],
            "error": False,
            "suggested_questions": build_preference_questions(preferences),
        }

    # 让 LLM 基于卡片 + query 写推荐话术
    if llm is None:
        answer = f"已为你找到 {len(results)} 款相似商品，你可以看下面的商品卡片。"
    else:
        prompt = _MULTIMODAL_SHOPPING_PROMPT.format(
            query_text=query_text or "（无文本描述，仅参考图片）",
            product_list=_format_products_for_prompt(results),
            preference_context=(
                str(preferences) if preferences else "（暂无长期偏好）"
            ),
        )
        try:
            if token_sink is None:
                resp = await llm.ainvoke(prompt)
                answer = str(getattr(resp, "content", "") or "").strip()
            else:
                chunks: list[str] = []
                async for chunk in llm.astream(prompt):
                    content = _stream_text_content(getattr(chunk, "content", ""))
                    if not content:
                        continue
                    chunks.append(content)
                    _emit_stream_token(token_sink, content)
                answer = "".join(chunks).strip()
        except Exception as e:  # noqa: BLE001
            logger.warning("multimodal shopping 生成推荐话术失败：%s", e)
            answer = ""
        if not answer:
            answer = f"已为你找到 {len(results)} 款相似商品，你可以看下面的商品卡片。"

    # 精简 product_cards 字段（去掉向量分数等评测字段）
    product_cards = []
    for r in results:
        product_cards.append({
            "product_id": r.get("product_id"),
            "title": r.get("title", ""),
            "brand": r.get("brand", ""),
            "price": r.get("price") or r.get("base_price"),
            "base_price": r.get("base_price"),
            "image_url": r.get("image_url", ""),
            "rating": r.get("rating"),
            "sales_count": r.get("sales_count"),
            "sub_category": r.get("sub_category", ""),
            "reason": (
                "图文检索命中；符合长期偏好："
                + "、".join((r.get("_personalization_matches") or [])[:2])
                if r.get("_personalization_matches")
                else "图文多模态检索命中"
            ),
            "_personalization_score": r.get("_personalization_score", 0.0),
            "_matched_preferences": r.get("_personalization_matches") or [],
            "_preference_conflicts": r.get("_personalization_conflicts") or [],
        })

    return {
        "answer": answer,
        "task_type": "shopping",
        "product_cards": product_cards,
        "sources": [],
            "tool_calls": [{
            "tool_name": "search_multimodal_v1",
            "input_params": {"query_text": query_text, "query_image_url": image_url, "top_k": top_k, "hard_filters": hard_filters, "retrieval_counts": retrieval_counts},
            "status": "completed",
            # Backward-compatible aliases used by existing tests/scripts.
            "name": "search_multimodal_v1",
            "args": {"query_text": query_text, "query_image_url": image_url, "top_k": top_k, "hard_filters": hard_filters, "retrieval_counts": retrieval_counts},
        }],
        "error": False,
        "suggested_questions": build_preference_questions(preferences),
    }


def _stream_text_content(content: Any) -> str:
    """Extract user-visible text from a LangChain stream chunk."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(part["text"])
            for part in content
            if isinstance(part, dict) and part.get("type") == "text" and part.get("text")
        )
    return ""


def _emit_stream_token(token_sink: Callable[[str], None], content: str) -> None:
    try:
        token_sink(content)
    except Exception:  # noqa: BLE001
        logger.debug("stream token sink unavailable", exc_info=True)


def _graph_token_sink(content: str) -> None:
    """Publish a real model chunk from a graph node to the SSE adapter."""
    if not content:
        return
    try:
        get_stream_writer()({"type": "token", "data": {"content": content}})
    except Exception:  # noqa: BLE001
        # Graph.run() uses ainvoke rather than a custom stream writer.
        logger.debug("graph token writer unavailable", exc_info=True)


def make_nodes(llm, shopping_agent: Optional[ShoppingAgent] = None,
               knowledge_agent: Optional[KnowledgeAgent] = None) -> Dict[str, Callable]:
    _shopping_holder: Dict[str, Any] = {"agent": shopping_agent}
    _knowledge_holder: Dict[str, Any] = {"agent": knowledge_agent}

    def get_shopping():
        if _shopping_holder["agent"] is None:
            _shopping_holder["agent"] = ShoppingAgent(llm)
        return _shopping_holder["agent"]

    def get_knowledge():
        if _knowledge_holder["agent"] is None:
            _knowledge_holder["agent"] = KnowledgeAgent(llm)
        return _knowledge_holder["agent"]

    async def shopping_node(state: AssistantState) -> dict:
        # 多模态分支：state 里有 image_url 时走图文多模态检索，
        # 不进 ShoppingAgent 的 LLM tool loop（文本 LLM 看不到图，让它决定
        # 要不要调多模态工具没意义）
        active_task = state.get("active_subtask") or {}
        image_allowed = not active_task or bool(active_task.get("use_image"))
        image_url = (state.get("image_url") or "").strip() if image_allowed else ""
        if image_url:
            try:
                persisted_memory = await get_business_memory(
                    state.get("conversation_id"), state.get("user_id"),
                )
            except Exception:  # noqa: BLE001
                persisted_memory = {}
            injected_memory = state.get("business_memory") or {}
            business_memory = {**persisted_memory, **injected_memory}
            result = await _multimodal_shopping(
                llm=llm,
                query_text=state.get("question", ""),
                image_url=image_url,
                top_k=5,
                business_memory=business_memory,
                token_sink=_graph_token_sink,
            )
            # Make image retrieval behave exactly like text recommendation on
            # the next turn.  Without this, "这两款对比" falls back to stale
            # cards produced by an earlier text-only recommendation.
            if result.get("product_cards"):
                try:
                    await remember_product_cards(
                        state.get("conversation_id"), state.get("user_id"),
                        result["product_cards"],
                    )
                except Exception:  # noqa: BLE001
                    logger.warning("multimodal product cards memory write failed", exc_info=True)
            return _merge_result(
                result,
                task_type="shopping",
                extra={"messages": [AIMessage(content=result.get("answer", ""))]},
            )

        try:
            result = await get_shopping().run(
                question=state.get("question", ""),
                # The Router already resolved cross-turn context and rewrote the
                # question.  Do not hand raw history to the domain tool loop and
                # accidentally create a second, competing reference resolver.
                messages=[{"role": "user", "content": state.get("question", "")}],
                business_memory=state.get("business_memory", {}),
                conversation_id=state.get("conversation_id"),
                user_id=state.get("user_id"),
                jwt_token=state.get("jwt_token"),
                token_sink=_graph_token_sink,
            )
        except Exception as e:
            logger.exception("shopping node failed")
            return {
                "answer": "导购 Agent 暂时不可用，请稍后再试。",
                "task_type": "shopping",
                "error": True,
                "error_code": ErrorCode.SHOPPING_ERROR,
                "message": str(e),
                "messages": [AIMessage(content="导购 Agent 暂时不可用，请稍后再试。")],
            }
        return _merge_result(result, task_type="shopping",
                             extra={"messages": [AIMessage(content=result.get("answer", ""))]})

    async def knowledge_node(state: AssistantState) -> dict:
        try:
            # KnowledgeAgent receives the canonical current question only.  Its
            # prior entity binding is already represented in that question by
            # the Router, so no full history or secondary context resolver is needed.
            messages = [HumanMessage(content=state.get("question", ""))]
            result = await get_knowledge().run(
                messages=messages,
                conversation_id=state.get("conversation_id", ""),
                user_id=state.get("user_id"),
            )
            # 无检索结果兜底：sources 为空 或 has_answer=False 时补一句引导，
            # 但 task_type 保持 knowledge —— 不要伪装成 chitchat，否则前端行为错乱。
            # 具体的"知识库暂无相关信息"由 KNOWLEDGE_PROMPT 约束 LLM 自己说，这里只做兜底 answer 补全。
            has_answer = bool(result.get("has_answer", True))
            sources = result.get("sources") or []
            answer = (result.get("answer") or "").strip()
            if (not has_answer or not sources) and not answer:
                question = state.get("question", "")
                answer = (
                    f"关于「{question}」，我在知识库里暂时没有找到直接相关的资料。"
                    f"你可以换个角度问我，或者提供更具体的场景（比如你的肤质、使用需求），我再帮你分析。"
                )
                result = {**result, "answer": answer}
        except Exception as e:
            logger.exception("knowledge node failed")
            return {
                "answer": "知识检索暂时不可用，请稍后再试。",
                "task_type": "knowledge",
                "error": True,
                "error_code": ErrorCode.KNOWLEDGE_ERROR,
                "message": str(e),
                "messages": [AIMessage(content="知识检索暂时不可用，请稍后再试。")],
            }
        return _merge_result(result, task_type="knowledge",
                             extra={"messages": [AIMessage(content=result.get("answer", ""))]})

    async def chitchat_node(state: AssistantState) -> dict:
        if llm is None:
            return {
                "answer": "AI 助手暂未配置，无法闲聊。",
                "task_type": "chitchat",
                "error": True,
                "error_code": ErrorCode.LLM_NOT_CONFIGURED,
            }
        try:
            messages = [
                SystemMessage(content=CHITCHAT_PROMPT.format(**_build_chitchat_prompt_context(state))),
                *_build_agent_messages(state),
            ]
            chunks: list[str] = []
            # recursion_limit=5：chitchat 正常 1-2 步就出结果，5 步防死循环
            async for chunk in llm.astream(messages):
                content = _stream_text_content(getattr(chunk, "content", ""))
                if not content:
                    continue
                chunks.append(content)
                _graph_token_sink(content)
            result = {"messages": [AIMessage(content="".join(chunks))]}
            # answer 直接从最后一条 AI 消息 content 提取（纯文本，可流式）。
            # 去 ToolStrategy 后不再有 structured_response，这里就是主路径。
            answer = ""
            for m in reversed(result.get("messages", [])):
                if isinstance(m, dict):
                    if m.get("type") == "ai" and m.get("content"):
                        answer = str(m.get("content", ""))
                        break
                else:
                    if getattr(m, "type", "") == "ai":
                        content = getattr(m, "content", "")
                        if isinstance(content, str) and content.strip():
                            answer = content
                            break
            answer = answer or "嗯嗯，我在呢~"
        except Exception as e:
            logger.exception("chitchat node failed")
            return {
                "answer": "闲聊回复失败，请稍后再试。",
                "task_type": "chitchat",
                "error": True,
                "error_code": ErrorCode.CHITCHAT_ERROR,
                "message": str(e),
                "messages": [AIMessage(content="闲聊回复失败，请稍后再试。")],
            }
        return {
            "answer": answer,
            "task_type": "chitchat",
            "messages": [AIMessage(content=answer)],
        }

    async def unknown_node(state: AssistantState) -> dict:
        msg = "我还不确定你的需求，请清楚描述想找的商品或想了解的问题。"
        return {
            "answer": msg,
            "task_type": "unknown",
            "messages": [AIMessage(content=msg)],
        }

    def format_response(state: AssistantState) -> dict:
        result = {
            "answer": state.get("answer", ""),
            "task_type": state.get("task_type") or state.get("route") or "unknown",
            "product_cards": state.get("product_cards", []),
            "sources": state.get("sources", []),
            "retrieved_contexts": state.get("retrieved_contexts", []),
            "tool_calls": state.get("tool_calls", []),
            "suggested_questions": state.get("suggested_questions", []),
            "run_id": state.get("run_id"),
            "trace_id": state.get("trace_id"),
            "route": state.get("route"),
            "route_reason": state.get("route_reason"),
            "route_confidence": state.get("route_confidence"),
            "route_source": state.get("route_source"),
            "rule_route": state.get("rule_route"),
            "rule_confidence": state.get("rule_confidence"),
            "rule_reason": state.get("rule_reason"),
            "llm_route": state.get("llm_route"),
            "llm_confidence": state.get("llm_confidence"),
            "llm_reason": state.get("llm_reason"),
            "route_fallback_used": bool(state.get("route_fallback_used")),
            "orchestrator_mode": state.get("orchestrator_mode"),
            "orchestrator_reason": state.get("orchestrator_reason"),
            "sub_questions": state.get("sub_questions", []),
            "sub_results": state.get("sub_results", []),
            "task_levels": state.get("task_levels", []),
            "error": bool(state.get("error", False)),
            "error_code": state.get("error_code"),
            "message": state.get("message"),
        }
        return {"result": result}

    return {
        "shopping_node": shopping_node,
        "knowledge_node": knowledge_node,
        "chitchat_node": chitchat_node,
        "unknown_node": unknown_node,
        "format_response": format_response,
    }


def _build_agent_messages(state: AssistantState) -> list:
    """Build the recent message list for Chitchat only.

    Shopping and Knowledge receive their Router-normalized question through
    dedicated paths; Chitchat keeps dialogue messages for natural conversation
    and explicit conversation-recall requests.
    """
    messages = state.get("messages") or []
    out = []
    for m in messages:
        if isinstance(m, dict):
            out.append(m)
            continue
        mtype = getattr(m, "type", "")
        content = getattr(m, "content", "")
        if isinstance(content, str) and content.strip():
            if mtype == "human":
                out.append(HumanMessage(content=content))
            elif mtype == "ai":
                out.append(AIMessage(content=content))
            elif mtype == "system":
                out.append(SystemMessage(content=content))
    return out


def _build_chitchat_prompt_context(state: AssistantState) -> dict[str, str]:
    """Return values for the explicit Chitchat prompt template.

    Prompt instructions and section layout intentionally remain in
    ``app.prompts.prompts.CHITCHAT_PROMPT``.  This helper only serializes the
    bounded turn data that is safe for the Chitchat Agent to read.
    """
    preferences = dict((state.get("business_memory") or {}).get("user_preferences") or {})
    profile = {
        "gender": state.get("gender") or preferences.get("gender") or "",
        "skin_type": state.get("skin_type") or preferences.get("skin_type") or "",
        "preference_tags": state.get("preference_tags") or preferences.get("preference_tags") or [],
    }
    profile = {key: value for key, value in profile.items() if value not in (None, "", [])}

    history_lines: list[str] = []
    for message in (state.get("messages") or [])[-10:]:
        if isinstance(message, dict):
            role = str(message.get("role") or "")
            content = str(message.get("content") or "").strip()
        else:
            role = str(getattr(message, "type", "") or "")
            content = str(getattr(message, "content", "") or "").strip()
        if role in {"human", "user"}:
            label = "用户"
        elif role in {"ai", "assistant"}:
            label = "助手"
        else:
            continue
        if content:
            history_lines.append(f"{label}：{content[:300]}")

    current_question = str(state.get("question") or "").strip()
    history_text = "\n".join(history_lines) if history_lines else "暂无"
    return {
        "user_profile": json.dumps(profile, ensure_ascii=False) if profile else "暂无",
        "recent_conversation": history_text,
        "current_question": current_question or "暂无",
    }


def _merge_result(result: Dict[str, Any], *, task_type: str,
                  extra: Dict[str, Any] = None) -> dict:
    merged: Dict[str, Any] = {}
    for key in (
        "answer", "product_cards", "sources", "tool_calls", "suggested_questions", "retrieved_contexts",
        "capability", "dispatch_source", "hard_constraint_violation", "error", "error_code", "message",
    ):
        if key in result:
            merged[key] = result[key]
    merged.setdefault("answer", "")
    merged.setdefault("task_type", result.get("task_type") or task_type)
    merged.setdefault("product_cards", [])
    merged.setdefault("sources", [])
    merged.setdefault("tool_calls", [])
    merged.setdefault("suggested_questions", [])
    merged.setdefault("error", False)
    if extra:
        merged.update(extra)
    return merged


def _history_messages(state: AssistantState) -> list:
    """构建传给 ShoppingAgent 的历史消息列表（dict 格式）。"""
    messages = state.get("messages") or []
    out = []
    for m in messages:
        if isinstance(m, dict):
            out.append(m)
            continue
        mtype = getattr(m, "type", "")
        content = getattr(m, "content", "")
        if mtype == "human":
            out.append({"role": "user", "content": content})
        elif mtype == "ai":
            out.append({"role": "assistant", "content": str(content) if not isinstance(content, str) else content})
        elif mtype == "system":
            out.append({"role": "system", "content": content})
    return out
