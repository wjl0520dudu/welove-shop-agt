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

config = Config()
logger = logging.getLogger("ai-service")