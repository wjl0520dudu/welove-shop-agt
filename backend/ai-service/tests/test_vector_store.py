import os

from rag.vector_store import MilvusVectorStore

os.environ["OPENAI_API_KEY"] = "sk-ZwGM6SW5SaUkjLn219uF8Jcb22H4rKipOwpqDTwMeYOvBUu8"           # 换成你的 key
os.environ["OPENAI_BASE_URL"] = "https://api.openai-proxy.org/v1"
os.environ["MILVUS_URL"] = "http://192.168.150.102:19530"

# 假设你的 config 有 MILVUS_COLLECTION，没有的话直接设环境变量
os.environ["MILVUS_COLLECTION"] = "test_hybrid"

from rag.models import DocumentChunk, ChunkMetadata, SearchRequest, MetadataFilter

store = MilvusVectorStore(collection_name="my_rag_collection")

# ── 插入几条测试数据 ──
chunks = [
    DocumentChunk(
        content="Milvus 是一个高性能向量数据库",
        metadata=ChunkMetadata(
            doc_id=1, doc_type="guide", chunk_type="text",
            category_id=10, source="milvus_intro.md",
            title="Milvus 简介", chunk_index=0,
        ),
    ),
    DocumentChunk(
        content="LangChain 提供了统一的 Embedding 接口",
        metadata=ChunkMetadata(
            doc_id=2, doc_type="faq", chunk_type="text",
            category_id=20, source="langchain.md",
            title="LangChain Embedding", chunk_index=0,
        ),
    ),
]

n = store.upsert_chunks(chunks)
print(f"插入了 {n} 条")

# ── 搜索 ──
req = SearchRequest(query="向量数据库", top_k=3)
results = store.search(req)
for r in results:
    print(f"  [{r.score:.4f}] {r.metadata.title}: {r.content[:40]}")

# ── 按 doc_id 删除 ──
deleted = store.delete_by_doc_id(1)
print(f"删除了 {deleted} 条")

# ── 统计 ──
print(store.stats())