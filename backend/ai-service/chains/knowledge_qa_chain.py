from langchain_core.output_parsers import StrOutputParser
import core.llm
from prompts.knowledge_qa import KNOWLEDGE_QA_PROMPT


def build_knowledge_qa_chain():
    """构建知识问答生成链。无 key 时返回 None。

    注意：Day18 不做检索，knowledge_context 由外部传入。
    """
    llm = core.llm.get_llm()
    if llm is None:
        return None
    return KNOWLEDGE_QA_PROMPT | llm | StrOutputParser()