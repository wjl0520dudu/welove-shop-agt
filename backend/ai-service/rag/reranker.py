"""DashScope qwen3-rerank HTTP client。

**为什么走 HTTP 而不是 dashscope SDK**：
- SDK 的 `dashscope.TextReRank.call` 历史上 API 参数名有变动，且专属部署端点用 SDK 更麻烦
- 官方直接给的就是 curl 例子，签名简单：一个 POST + Bearer token
- 走 HTTP 我们完全控制超时、失败降级、错误分类

**两阶段检索的位置**：
    hybrid_search(top_k=initial_top_k=20)
        ↓
    reranker.rerank(query, docs, top_n=5)
        ↓
    final top_k=5

**降级策略**：任何异常（网络/超时/HTTP 5xx/字段缺失）都不抛，日志 warn 后返回原顺序。
理由：rerank 是"锦上添花"，不能让它挂了整个 knowledge 检索就死。
"""

from __future__ import annotations

import logging
from typing import List, Optional

import httpx

from core.config import config

logger = logging.getLogger("ai-service.rag.reranker")


class DashScopeReranker:
    """DashScope 通用文本排序（qwen3-rerank）客户端。

    单例访问：`get_reranker()`。
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        endpoint: str | None = None,
        timeout: float | None = None,
    ):
        self.api_key = api_key or config.DASH_SCOPE_API_KEY
        self.model = model or config.DASH_SCOPE_TEXT_RERANK_MODEL
        self.endpoint = endpoint or config.DASH_SCOPE_RERANK_URL
        self.timeout = timeout if timeout is not None else config.DASH_SCOPE_RERANK_TIMEOUT

        if not self.api_key:
            raise ValueError(
                "DASH_SCOPE_API_KEY 未配置，rerank 无法使用。请在 .env 里补上。"
            )

    def rerank(
        self,
        query: str,
        documents: List[str],
        top_n: Optional[int] = None,
    ) -> List[tuple[int, float]]:
        """对 documents 相对 query 重新排序。

        Args:
            query: 用户问题原文
            documents: 候选文本列表（Milvus 一路召回的 chunk.content）
            top_n: 返回前 N 条；None = 返回全部（按新分数降序）

        Returns:
            [(原索引 idx_in_documents, relevance_score), ...] 按 relevance_score 降序。
            **重排失败时返回 [(0, 0), (1, 0), ...] 保持原顺序**（不抛异常）。
        """
        if not documents:
            return []
        if not query or not query.strip():
            # 空 query 没意义 rerank，直接返回原顺序
            return [(i, 0.0) for i in range(len(documents))]

        n = top_n if top_n is not None else len(documents)

        payload = {
            "model": self.model,
            "input": {
                "query": query,
                "documents": documents,
            },
            "parameters": {
                # return_documents=False：省流量，我们本来就有 documents，只要 index+score
                "return_documents": False,
                "top_n": n,
            },
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    self.endpoint,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException:
            logger.warning("rerank 超时（%ss），退回原顺序", self.timeout)
            return [(i, 0.0) for i in range(len(documents))]
        except httpx.HTTPStatusError as e:
            body = ""
            try:
                body = e.response.text[:300]
            except Exception:
                pass
            logger.warning("rerank HTTP %d，退回原顺序：%s", e.response.status_code, body)
            return [(i, 0.0) for i in range(len(documents))]
        except Exception as e:  # noqa: BLE001
            logger.warning("rerank 异常，退回原顺序：%s", e)
            return [(i, 0.0) for i in range(len(documents))]

        # ── 解析返回 ──
        # 期望结构：
        #   {"output": {"results": [{"index": 0, "relevance_score": 0.87}, ...]},
        #    "usage": {...}, "request_id": "..."}
        # 兼容性防守：字段缺失就退回原顺序
        try:
            results = (data.get("output") or {}).get("results") or []
            if not results:
                logger.warning("rerank 返回 results 为空，退回原顺序：%s", str(data)[:200])
                return [(i, 0.0) for i in range(len(documents))]

            parsed: list[tuple[int, float]] = []
            for r in results:
                idx = r.get("index")
                score = r.get("relevance_score")
                if idx is None or score is None:
                    continue
                parsed.append((int(idx), float(score)))

            if not parsed:
                return [(i, 0.0) for i in range(len(documents))]
            return parsed
        except Exception as e:  # noqa: BLE001
            logger.warning("rerank 结果解析失败，退回原顺序：%s", e)
            return [(i, 0.0) for i in range(len(documents))]


# ── 单例访问 ─────────────────────────────────────────────
_reranker_instance: DashScopeReranker | None = None


def get_reranker() -> DashScopeReranker:
    """懒加载单例 DashScopeReranker。首次访问触发实例化。"""
    global _reranker_instance
    if _reranker_instance is None:
        _reranker_instance = DashScopeReranker()
    return _reranker_instance
