from langchain_core.output_parsers import StrOutputParser
import core.llm
from prompts.shopping import SHOPPING_QA_PROMPT


def build_shopping_chain():
    """构建导购话术生成链。无 key 时返回 None。"""
    llm = core.llm.get_llm()
    if llm is None:
        return None
    return SHOPPING_QA_PROMPT | llm | StrOutputParser()