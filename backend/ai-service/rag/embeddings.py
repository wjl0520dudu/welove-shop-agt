"""DashScope text-embedding-v4 wrapper。

为什么单独一层：
- 原来 vector_store.py 直接调 langchain_openai.OpenAIEmbeddings，dim 硬编码 1536，
  跟 DashScope text-embedding-v4（默认 1024）对不上。
- LangChain 的 dashscope embeddings 集成不稳定，且不支持我们要的 dimension 参数。
- 直接用官方 dashscope SDK 更可控——就是一个 `TextEmbedding.call()`。

设计要点：
- **batch 自动切片**：DashScope 单次最多 10 条，超过要拆。
- **接口和 langchain Embeddings 保持一致**：暴露 `embed_query` / `embed_documents`，
  这样 vector_store 里换实现只用改 get_embeddings() 一处。
- **维度可配**：走 config.MILVUS_DENSE_DIM，默认 1024。
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import List

import dashscope
from dashscope import TextEmbedding

from core.config import config

logger = logging.getLogger("ai-service.rag.embeddings")


class DashScopeEmbeddings:
    """DashScope text-embedding-v4 客户端。

    行为：
    - `embed_query(text)` → List[float]
    - `embed_documents(texts)` → List[List[float]]

    失败策略：一批调用返回非 200 就抛异常 —— 让上游知道 embedding 挂了，
    不静默返回空向量（否则会写空向量进 Milvus，检索永远召不回）。
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        dimension: int | None = None,
        batch_size: int | None = None,
    ):
        self.api_key = api_key or config.DASH_SCOPE_API_KEY
        self.model = model or config.DASH_SCOPE_TEXT_EMBEDDING_MODEL
        self.dimension = dimension or config.MILVUS_DENSE_DIM
        self.batch_size = batch_size or config.DASH_SCOPE_EMBEDDING_BATCH_SIZE

        if not self.api_key:
            raise ValueError(
                "DASH_SCOPE_API_KEY 未配置，无法使用 DashScope embedding。请在 .env 里补上。"
            )

        # dashscope SDK 用全局 api_key，第一次 import 时可能已被其他模块设置过——
        # 这里显式赋值确保和当前实例锁定的 key 一致。
        dashscope.api_key = self.api_key

    # ── LangChain Embeddings 接口兼容 ────────────────────────────────
    def embed_query(self, text: str) -> List[float]:
        vectors = self._call([text])
        return vectors[0]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            vectors = self._call(batch)
            out.extend(vectors)
        return out

    # ── 单次 SDK 调用（≤ batch_size 条）─────────────────────────────
    def _call(self, texts: List[str]) -> List[List[float]]:
        # DashScope 对空串会 400，先过滤——但保留位置，返回时补零向量
        # 让上游能按索引对齐（避免调用方以为 batch=3 却只拿到 2 个向量）。
        # 空串在业务里通常是脏数据，配一条 warn 让人早发现。
        cleaned: list[tuple[int, str]] = []
        for idx, t in enumerate(texts):
            if t and t.strip():
                cleaned.append((idx, t))
            else:
                logger.warning("DashScope embedding: 第 %d 条为空，将补零向量", idx)

        result_map: dict[int, list[float]] = {}
        if cleaned:
            resp = TextEmbedding.call(
                model=self.model,
                input=[t for _, t in cleaned],
                dimension=self.dimension,
            )
            if resp.status_code != HTTPStatus.OK:
                raise RuntimeError(
                    f"DashScope embedding 调用失败: status={resp.status_code} "
                    f"code={getattr(resp, 'code', '')} message={getattr(resp, 'message', '')}"
                )
            embeddings = (resp.output or {}).get("embeddings") or []
            # DashScope 按 input 顺序返回，embedding 里的 "text_index" 也能拿到——
            # 用 text_index 更保险（虽然文档说是顺序的，但保底还是按官方字段来）。
            for item in embeddings:
                orig_idx = cleaned[item["text_index"]][0]
                result_map[orig_idx] = item["embedding"]

        # 按原顺序拼回；空串位置补零向量
        zero_vec = [0.0] * self.dimension
        return [result_map.get(i, zero_vec) for i in range(len(texts))]


# ── 单例访问器 ───────────────────────────────────────────────────
_embeddings_instance: DashScopeEmbeddings | None = None


def get_embeddings() -> DashScopeEmbeddings:
    """返回单例 DashScopeEmbeddings。

    保持"函数入口"是为了让 vector_store 里 `get_embeddings()` 的调用方式不变——
    历史上 `get_embeddings()` 返回的是 OpenAIEmbeddings，现在换成 DashScope 但接口一致。
    """
    global _embeddings_instance
    if _embeddings_instance is None:
        _embeddings_instance = DashScopeEmbeddings()
    return _embeddings_instance
