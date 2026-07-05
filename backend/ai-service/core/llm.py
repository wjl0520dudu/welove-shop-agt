from core.config import config


def get_llm():
    """返回 LLM 实例，未配置 key 时返回 None。"""
    if not config.LLM_API_KEY:
        return None
    from langchain.chat_models import init_chat_model
    return init_chat_model(
        model=config.LLM_MODEL,
        api_key=config.LLM_API_KEY,
        base_url=config.LLM_BASE_URL,
        temperature=0,
        model_provider=config.MODEL_PROVIDER,
    )


llm = get_llm()
response = llm.invoke("翻译如下的汉字：你好世界")
print(response)
