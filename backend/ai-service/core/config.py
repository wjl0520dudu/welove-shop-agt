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
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    MILVUS_URL = os.getenv("MILVUS_URL", "http://127.0.0.1:19530")
    MILVUS_COLLECTION = os.getenv("MILVUS_COLLECTION", "my_rag_collection")

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
    JAVA_API_BASE_URL = os.getenv("JAVA_API_BASE_URL", "http://localhost:8888")
    JAVA_API_TIMEOUT_SECONDS = float(os.getenv("JAVA_API_TIMEOUT_SECONDS", "10"))

    # 7. LangSmith tracing（可观测性）
    # LANGSMITH_TRACING=true 开启后 LangChain 自动上报所有 invoke/ainvoke/astream 到 LangSmith
    LANGSMITH_TRACING = os.getenv("LANGSMITH_TRACING", "false").lower() in ("1", "true", "yes")
    LANGSMITH_ENDPOINT = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
    LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY", "")
    LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "welove-shop-ai")


config = Config()
logger = logging.getLogger("ai-service")
