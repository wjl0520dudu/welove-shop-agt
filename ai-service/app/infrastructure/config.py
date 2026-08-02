import os
import logging
from dotenv import load_dotenv
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(ENV_FILE, override=True)

class Config:
    # 加载环境变量
    # 1.大模型配置
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
    LLM_MODEL = os.getenv("LLM_MODEL", "")
    MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "openai")  # 模型提供商，默认为 openai

    # 1a. Orchestrator DAG 配置
    ORCHESTRATOR_MAX_TASKS = int(os.getenv("ORCHESTRATOR_MAX_TASKS", "5"))
    ORCHESTRATOR_MAX_DEPTH = int(os.getenv("ORCHESTRATOR_MAX_DEPTH", "4"))
    ORCHESTRATOR_MAX_CONCURRENCY = int(os.getenv("ORCHESTRATOR_MAX_CONCURRENCY", "3"))
    ORCHESTRATOR_TASK_TIMEOUT_SECONDS = float(os.getenv("ORCHESTRATOR_TASK_TIMEOUT_SECONDS", "30"))

    # 1b. Low-cost hybrid router. Rules only claim high-certainty cases; unresolved
    # requests use one structured LLM call and low-confidence results ask for clarification.
    ROUTER_RULE_MIN_CONFIDENCE = float(os.getenv("ROUTER_RULE_MIN_CONFIDENCE", "0.90"))
    ROUTER_LOW_CONFIDENCE_THRESHOLD = float(os.getenv("ROUTER_LOW_CONFIDENCE_THRESHOLD", "0.65"))
    ROUTER_ORCHESTRATOR_HINT_CONFIDENCE = float(
        os.getenv("ROUTER_ORCHESTRATOR_HINT_CONFIDENCE", "0.90")
    )

    # 1c. Preference-aware soft reranking. These are bounded adjustments applied
    # after relevance retrieval; current-turn hard constraints remain authoritative.
    PERSONALIZATION_POSITIVE_BOOST = float(os.getenv("PERSONALIZATION_POSITIVE_BOOST", "0.08"))
    PERSONALIZATION_NEGATIVE_PENALTY = float(os.getenv("PERSONALIZATION_NEGATIVE_PENALTY", "0.12"))
    PERSONALIZATION_MULTIMODAL_WEIGHT = float(os.getenv("PERSONALIZATION_MULTIMODAL_WEIGHT", "0.15"))

    # 2.RAG 文档分块配置
    CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))
    CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "120"))
    # Requires a dedicated/reindexed collection that persists parent_id.  Keep
    # false until the migration script has built and validated that index.
    RAG_PARENT_CHILD_ENABLED = os.getenv("RAG_PARENT_CHILD_ENABLED", "false").lower() in ("1", "true", "yes")
    # Defaults to the v2.3 recursive implementation.  ``fixed_v1`` is a
    # separately indexed experiment and never changes the default behavior.
    RAG_PARENT_CHILD_CHUNKING = os.getenv("RAG_PARENT_CHILD_CHUNKING", "recursive_v23").strip().lower()
    # Mixed indexes keep product semantic units as direct retrieval records
    # while only general knowledge uses parent-child storage/reconstruction.
    # This must stay false for the historical all-parent-child collections.
    RAG_PARENT_CHILD_GENERAL_ONLY = os.getenv(
        "RAG_PARENT_CHILD_GENERAL_ONLY", "false"
    ).lower() in ("1", "true", "yes")

    # 3.向量库和 embedding 配置
    # ── OpenAI 兼容通道（历史遗留，暂不删）──
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

    # ── Milvus ──
    MILVUS_URL = os.getenv("MILVUS_URL", "http://127.0.0.1:19530")
    # Zilliz Cloud uses the same PyMilvus API but requires a token.  Keep this
    # optional so local unauthenticated Milvus deployments remain compatible.
    MILVUS_TOKEN = os.getenv("MILVUS_TOKEN", "")
    MILVUS_COLLECTION = os.getenv("MILVUS_COLLECTION", "my_rag_collection")
    # 稠密向量维度：DashScope text-embedding-v4 支持 2048/1536/1024/768/512/256/128/64，
    # 我们锁 1024（在检索质量和存储/召回速度间平衡最好）。
    # 改这个字段前先跑 drop_milvus_collection.py 清库，否则 schema dim 不一致会插入失败。
    MILVUS_DENSE_DIM = int(os.getenv("MILVUS_DENSE_DIM", "1024"))

    # ── 商品多模态 collection（Phase 1b 起启用）──
    # 商品向量迁移到独立 collection，跟知识 collection 隔离；
    # schema 里预留 multimodal_vector 字段，Phase 2 图片就绪后灌图+文融合向量。
    MILVUS_PRODUCT_COLLECTION = os.getenv("MILVUS_PRODUCT_COLLECTION", "product_mm_collection")

    # ── 商品多模态 v2 collection（实验链路，不影响线上旧 collection）──
    # product_mm_v2 用于评测图文混合召回：text_dense + BM25 + image_vector + multimodal_vector。
    MILVUS_PRODUCT_V2_COLLECTION = os.getenv("MILVUS_PRODUCT_V2_COLLECTION", "product_mm_v2")
    # 生产三路检索：text dense + BM25 + image，不写图文融合向量。
    MILVUS_PRODUCT_THREE_PATH_COLLECTION = os.getenv(
        "MILVUS_PRODUCT_THREE_PATH_COLLECTION", "product_multimodal_prod_v1",
    )
    SHOPPING_MULTIMODAL_USE_THREE_PATH_COLLECTION = os.getenv(
        "SHOPPING_MULTIMODAL_USE_THREE_PATH_COLLECTION", "false",
    ).lower() in ("1", "true", "yes")
    MILVUS_IMAGE_DIM = int(os.getenv("MILVUS_IMAGE_DIM", "2560"))
    MILVUS_MULTIMODAL_DIM = int(os.getenv("MILVUS_MULTIMODAL_DIM", "2560"))

    # tongyi-embedding-vision-flash（图+文多模态 embedding，Phase 2 启用）
    # MVP（Phase 1b）：商品文本向量仍走 DashScope text-embedding-v4，跟 KnowledgeAgent 保持同一 embedding。
    # 只有 multimodal_vector 字段等 Phase 2 才用 tongyi。
    DASH_SCOPE_MULTI_MODAL_EMBEDDING_MODEL = os.getenv(
        "DASH_SCOPE_MULTI_MODAL_EMBEDDING_MODEL", "qwen3-vl-embedding",
    )
    DASH_SCOPE_MULTI_MODAL_RERANK_MODEL = os.getenv("DASH_SCOPE_MULTI_MODAL_RERANK_MODEL", "qwen3-vl-rerank")
    # 商品检索二次相关性审核；模型不支持图片时自动降级到品类一致性过滤。
    SHOPPING_LLM_JUDGE_ENABLED = os.getenv("SHOPPING_LLM_JUDGE_ENABLED", "true").lower() in ("1", "true", "yes")
    SHOPPING_LLM_JUDGE_MAX_CANDIDATES = int(os.getenv("SHOPPING_LLM_JUDGE_MAX_CANDIDATES", "10"))
    SHOPPING_LLM_JUDGE_MIN_SCORE = float(os.getenv("SHOPPING_LLM_JUDGE_MIN_SCORE", "0.55"))
    # ShoppingAgent Deep Agents + Skills dual-track switch.  The Skill-driven
    # runtime is the default; set false for an explicit manual rollback.
    SHOPPING_DEEP_AGENT_ENABLED = os.getenv(
        "SHOPPING_DEEP_AGENT_ENABLED", "true"
    ).lower() in ("1", "true", "yes")
    # Virtual path inside the read-only ai-service filesystem backend.
    SHOPPING_SKILLS_ROOT = os.getenv(
        "SHOPPING_SKILLS_ROOT", "/skills/shopping-agent/"
    )
    # KnowledgeAgent Deep Agents + Skills runtime. The old LangChain agent is
    # retained only for an explicit manual rollback.
    KNOWLEDGE_DEEP_AGENT_ENABLED = os.getenv(
        "KNOWLEDGE_DEEP_AGENT_ENABLED", "true"
    ).lower() in ("1", "true", "yes")
    KNOWLEDGE_SKILLS_ROOT = os.getenv(
        "KNOWLEDGE_SKILLS_ROOT", "/skills/knowledge-agent/"
    )
    # Reviewed Skill scripts execute through a fixed whitelist runner. Generic
    # shell/Deep Agents execute remains hidden from ShoppingAgent.
    SHOPPING_SKILL_SCRIPT_MODE = os.getenv(
        "SHOPPING_SKILL_SCRIPT_MODE", "controlled"
    ).strip().lower()
    SHOPPING_SKILL_SCRIPT_TIMEOUT_SECONDS = float(os.getenv(
        "SHOPPING_SKILL_SCRIPT_TIMEOUT_SECONDS", "2"
    ))
    # DashScope's multimodal SDK is synchronous.  The shopping retrieval
    # wrapper runs it in a bounded worker and uses this as the total request
    # budget, so a stalled third-party call cannot block FastAPI's event loop.
    SHOPPING_MULTIMODAL_RETRIEVAL_TIMEOUT_SECONDS = float(os.getenv(
        "SHOPPING_MULTIMODAL_RETRIEVAL_TIMEOUT_SECONDS", "12"
    ))
    # 多模态 embedding / rerank 走百炼业务空间专属端点；不配置时使用 dashscope SDK 默认端点。
    DASHSCOPE_MAAS_BASE_URL = os.getenv("DASHSCOPE_MAAS_BASE_URL", "")

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
    # 单实例单库 + 多 schema：Java 微服务和 Python ai-service 共用同一个 PG 库，
    # 通过 schema 隔离业务（product_svc / user_svc / trade_svc / chat_svc / admin_svc）。
    PG_BUSINESS_DB = os.getenv("PG_BUSINESS_DB", "welove_shop_search")
    # 业务库 search_path：连接后自动 SET，让 ORM 无前缀直接命中对应 schema 的表。
    # 顺序按业务模块归属决定（product/user/trade/chat 优先命中自己的 schema，public 兜底）。
    PG_BUSINESS_SEARCH_PATH = os.getenv(
        "PG_BUSINESS_SEARCH_PATH",
        "product_svc, user_svc, trade_svc, chat_svc, admin_svc, public",
    )

    # 5c. 商品图片 CDN base URL（多模态 embedding / rerank 调用时把相对路径拼成绝对 URL）
    # PG.product.image_url 存的是相对路径（/weloveshop/products/xxx.jpg），前端拼接 CDN；
    # DashScope multimodal API 要求 HTTP/HTTPS 绝对 URL，所以后端调用前也得拼。
    IMAGE_BASE_URL = os.getenv("IMAGE_BASE_URL", "https://liangwenjun.oss-cn-hangzhou.aliyuncs.com")

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
    LANGSMITH_ENVIRONMENT = os.getenv("LANGSMITH_ENVIRONMENT", "development")
    # LangSmith receives runnable inputs/outputs by default.  Keep the
    # production-safe default masked; a local developer can explicitly opt in
    # while diagnosing prompts and tool payloads.
    LANGSMITH_HIDE_INPUTS = os.getenv("LANGSMITH_HIDE_INPUTS", "true").lower() in ("1", "true", "yes")
    LANGSMITH_HIDE_OUTPUTS = os.getenv("LANGSMITH_HIDE_OUTPUTS", "true").lower() in ("1", "true", "yes")

    # 8. CORS 允许来源。逗号分隔多个源；"*" 表示允许所有（仅开发/内网）。
    # 生产环境建议明确列出前端域名（如 https://shop.welove.com,http://localhost:5173），
    # 不建议直接开 "*"。
    ALLOWED_ORIGINS = [
        o.strip() for o in os.getenv(
            "ALLOWED_ORIGINS",
            "http://localhost:5173,http://localhost:8080,http://127.0.0.1:5173,http://127.0.0.1:8080",
        ).split(",") if o.strip()
    ]

    # 9. 博查 Web 搜索兜底（KnowledgeAgent 内部知识库不足时自动触发）
    # 不配置 BOCHA_API_KEY 时不启用兜底，KnowledgeAgent 行为不变。
    BOCHA_API_KEY = os.getenv("BOCHA_API_KEY", "")
    # 博查 MCP Server 启动方式：默认 "uvx"（uv 一键运行），也可换成 "npx" 或直接 HTTP。
    BOCHA_MCP_COMMAND = os.getenv("BOCHA_MCP_COMMAND", "uvx")
    # 博查兜底超时（秒）。兜底不应拖慢主流程，默认 5s。
    BOCHA_SEARCH_TIMEOUT = float(os.getenv("BOCHA_SEARCH_TIMEOUT", "5.0"))


config = Config()
logger = logging.getLogger("ai-service")
