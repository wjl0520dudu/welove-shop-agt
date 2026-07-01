from core.config import config


def get_llm():
    """返回 LLM 实例，未配置 key 时返回 None。"""
    if not config.LLM_API_KEY:
        return None
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=config.LLM_MODEL,
        api_key=config.LLM_API_KEY,
        base_url=config.LLM_BASE_URL,
        temperature=0,
    )