from langchain_core.prompts import PromptTemplate

TITLE_QA_PROMPT = PromptTemplate.from_template(
    """
    请为以下用户问题生成一个简短的标题（Summary）。

    用户问题：
    {question}

    要求：
    1. 标题应概括问题的主要内容。
    2. 长度控制在10个字以内。
    3. 不需要任何前缀或后缀，直接返回标题文本。

    标题：
    """
)