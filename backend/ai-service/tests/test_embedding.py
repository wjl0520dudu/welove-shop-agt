import os

import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_EMBEDDING_TESTS") != "1",
    reason="Embedding integration test requires RUN_EMBEDDING_TESTS=1 and OPENAI_API_KEY.",
)


def test_embedding_provider_returns_vector():
    from rag.vector_store import get_embeddings

    vector = get_embeddings().embed_query("你好，世界")
    assert isinstance(vector, list)
    assert len(vector) > 0
