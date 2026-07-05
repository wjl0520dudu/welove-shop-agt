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

    # 4.MySQL 配置，用于导购推荐查询真实商品数据
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = int(os.getenv("DB_PORT", "3306"))
    DB_NAME = os.getenv("DB_NAME", "welove_shop_db")
    DB_USER = os.getenv("DB_USER", "root")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")
    DB_CHARSET = os.getenv("DB_CHARSET", "utf8mb4")


config = Config()
logger = logging.getLogger("ai-service")
