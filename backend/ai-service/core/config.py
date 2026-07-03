import os
import logging
from dotenv import load_dotenv

load_dotenv()

class Config:
    # 加载环境变量
    # 1.大模型配置
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
    LLM_MODEL = os.getenv("LLM_MODEL", "")

    # 2.RAG 文档分块配置
    CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))
    CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "120"))

    # 3.向量库和 embedding 配置
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    MILVUS_URL = os.getenv("MILVUS_URL", "http://127.0.0.1:19530")
    MILVUS_COLLECTION = os.getenv("MILVUS_COLLECTION", "my_rag_collection")

config = Config()
logger = logging.getLogger("ai-service")
