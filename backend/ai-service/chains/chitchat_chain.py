from langchain_core.output_parsers import StrOutputParser
import core.llm
from prompts.chitchat import CHITCHAT_PROMPT


def build_chitchat_chain():
    """构建闲聊链：prompt | llm | StrOutputParser。无 key 时返回 None。"""
    llm = core.llm.get_llm()
    if llm is None:
        return None
    return CHITCHAT_PROMPT | llm | StrOutputParser()