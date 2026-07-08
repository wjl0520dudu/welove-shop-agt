import os
import logging
from dotenv import load_dotenv
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(ENV_FILE, override=True)

class Config:
    # 加载环境变量
    # 1.大模型配置
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
    LLM_MODEL = os.getenv("LLM_MODEL", "")
    MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "openai")  # 模型提供商，默认为 openai

    # 2.RAG 文档分块配置
    CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))
    CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "120"))

    # 3.向量库和 embedding 配置
    # ── OpenAI 兼容通道（历史遗留，暂不删）──
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

    # ── Milvus ──
    MILVUS_URL = os.getenv("MILVUS_URL", "http://127.0.0.1:19530")
    MILVUS_COLLECTION = os.getenv("MILVUS_COLLECTION", "my_rag_collection")
    # 稠密向量维度：DashScope text-embedding-v4 支持 2048/1536/1024/768/512/256/128/64，
    # 我们锁 1024（在检索质量和存储/召回速度间平衡最好）。
    # 改这个字段前先跑 drop_milvus_collection.py 清库，否则 schema dim 不一致会插入失败。
    MILVUS_DENSE_DIM = int(os.getenv("MILVUS_DENSE_DIM", "1024"))

    # ── 商品多模态 collection（Phase 1b 起启用）──
    # 商品向量迁移到独立 collection，跟知识 collection 隔离；
    # schema 里预留 multimodal_vector 字段，Phase 2 图片就绪后灌图+文融合向量。
    MILVUS_PRODUCT_COLLECTION = os.getenv("MILVUS_PRODUCT_COLLECTION", "product_mm_collection")

    # tongyi-embedding-vision-flash（图+文多模态 embedding，Phase 2 启用）
    # MVP（Phase 1b）：商品文本向量仍走 DashScope text-embedding-v4，跟 KnowledgeAgent 保持同一 embedding。
    # 只有 multimodal_vector 字段等 Phase 2 才用 tongyi。
    DASH_SCOPE_MULTI_MODAL_EMBEDDING_MODEL = os.getenv(
        "DASH_SCOPE_MULTI_MODAL_EMBEDDING_MODEL", "tongyi-embedding-vision-flash-2026-03-06",
    )

    # ── DashScope（阿里云百炼）text-embedding-v4 ──
    # 现在是主用 embedding 通道（RAG 的 dense 向量走这里），OpenAI 通道保留仅供兼容。
    DASH_SCOPE_API_KEY = os.getenv("DASH_SCOPE_API_KEY", "")
    DASH_SCOPE_TEXT_EMBEDDING_MODEL = os.getenv("DASH_SCOPE_TEXT_EMBEDDING_MODEL", "text-embedding-v4")
    # DashScope 单次最大 batch=10，超出会 400。
    DASH_SCOPE_EMBEDDING_BATCH_SIZE = int(os.getenv("DASH_SCOPE_EMBEDDING_BATCH_SIZE", "10"))

    # ── DashScope rerank（qwen3-rerank）──
    # 两阶段检索用：Milvus hybrid 先召回 initial_top_k（20），再让 rerank 精排到 top_k（5）。
    # 走 HTTP 直调 —— 官方给的就是 curl 例子，signature 简单。
    #
    # 端点选公共 dashscope.aliyuncs.com：专属部署（llm-ng848...maas.aliyuncs.com）
    # 不带 rerank 服务，实测 400 InvalidParameter；用公共端点 qwen3-rerank 200 OK。
    DASH_SCOPE_RERANK_URL = os.getenv(
        "DASH_SCOPE_RERANK_URL",
        "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
    )
    DASH_SCOPE_TEXT_RERANK_MODEL = os.getenv("DASH_SCOPE_TEXT_RERANK_MODEL", "qwen3-rerank")
    DASH_SCOPE_RERANK_TIMEOUT = float(os.getenv("DASH_SCOPE_RERANK_TIMEOUT", "5.0"))

    # ── RAG 两阶段检索参数 ──
    # 初始召回数：hybrid 从 Milvus 拿多少候选送给 rerank。20 是经验值——
    # 太少（<10）rerank 挑不出好的；太多（>50）rerank 延迟涨得不划算。
    RAG_INITIAL_TOP_K = int(os.getenv("RAG_INITIAL_TOP_K", "20"))

    # 4.MySQL 配置（历史遗留）
    # ai-service 主库已迁移到 PostgreSQL。这里保留仅供 sync_mysql_to_pg.py 从 MySQL 拉数据到 PG。
    # Java 那边完成迁移后可以彻底删除。
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = int(os.getenv("DB_PORT", "3306"))
    DB_NAME = os.getenv("DB_NAME", "welove_shop_db")
    DB_USER = os.getenv("DB_USER", "root")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")
    DB_CHARSET = os.getenv("DB_CHARSET", "utf8mb4")

    # 5.PostgreSQL 共用配置（一个实例，两个库）
    PG_HOST = os.getenv("PG_HOST", "localhost")
    PG_PORT = int(os.getenv("PG_PORT", "5432"))
    PG_USER = os.getenv("PG_USER", "root")
    PG_PASSWORD = os.getenv("PG_PASSWORD", "")

    # 5a. pgvector + langgraph 记忆库（商品向量、checkpointer、store）
    # 保留 PG_NAME 作为向后兼容别名 —— 老代码可能直接用它。
    PG_LANGGRAPH_DB = os.getenv("PG_LANGGRAPH_DB", os.getenv("PG_NAME", "welove_shop_search"))
    PG_NAME = PG_LANGGRAPH_DB  # 别名，保持兼容

    # 5b. 业务主库（商品、用户、购物车等，从 MySQL 迁过来）
    # Java 完成迁移后也接这个库。
    PG_BUSINESS_DB = os.getenv("PG_BUSINESS_DB", "welove_shop_db")

    # 6. Java 后端服务地址（Python agent 通过 HTTP 调 Java 拿业务数据：收藏/浏览/订单）
    # ⚠️ 超时默认 2s：Java 挂了时快速失败，走 PG ORM 降级路径，避免每个工具调用卡 10s。
    # 如果生产 Java 响应本身就慢，可通过 env 拉到 5-10s。
    JAVA_API_BASE_URL = os.getenv("JAVA_API_BASE_URL", "http://localhost:8888")
    JAVA_API_TIMEOUT_SECONDS = float(os.getenv("JAVA_API_TIMEOUT_SECONDS", "2"))

    # 7. LangSmith tracing（可观测性）
    # LANGSMITH_TRACING=true 开启后 LangChain 自动上报所有 invoke/ainvoke/astream 到 LangSmith
    LANGSMITH_TRACING = os.getenv("LANGSMITH_TRACING", "false").lower() in ("1", "true", "yes")
    LANGSMITH_ENDPOINT = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
    LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY", "")
    LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "welove-shop-ai")

    # 8. CORS 允许来源。逗号分隔多个源；"*" 表示允许所有（仅开发/内网）。
    # 生产环境建议明确列出前端域名（如 https://shop.welove.com,http://localhost:5173），
    # 不建议直接开 "*"。
    ALLOWED_ORIGINS = [
        o.strip() for o in os.getenv(
            "ALLOWED_ORIGINS",
            "http://localhost:5173,http://localhost:8080,http://127.0.0.1:5173,http://127.0.0.1:8080",
        ).split(",") if o.strip()
    ]


config = Config()
logger = logging.getLogger("ai-service")
