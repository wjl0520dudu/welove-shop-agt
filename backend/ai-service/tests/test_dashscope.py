import os
from http import HTTPStatus

import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DASHSCOPE_TESTS") != "1",
    reason="DashScope integration test requires RUN_DASHSCOPE_TESTS=1 and DASHSCOPE_API_KEY.",
)


def test_dashscope_embedding_returns_dense_and_sparse_vectors():
    import dashscope

    dashscope.api_key = os.getenv("DASHSCOPE_API_KEY", "")
    response = dashscope.TextEmbedding.call(
        model="text-embedding-v4",
        input="向量检索测试",
        parameters={"output_type": "dense&sparse"},
    )

    assert response.status_code == HTTPStatus.OK
    embedding = response.output.embeddings[0]
    assert embedding["dense_embedding"]
    assert embedding["sparse_embedding"]
