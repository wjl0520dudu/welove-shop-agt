from chains.chitchat_chain import build_chitchat_chain


def stream_chitchat(question, conversation_context="", user_profile=""):
    chain = build_chitchat_chain()
    if chain is None:
        yield "我是小智，暂时无法回复，请联系管理员配置 API key。"
        return
    for chunk in chain.stream({
        "question": question,
        "conversation_context": conversation_context,
        "user_profile": user_profile,
    }):
        yield chunk
