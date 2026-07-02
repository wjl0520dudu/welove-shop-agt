import os

from langchain_openai import OpenAIEmbeddings

em = OpenAIEmbeddings(
        model="Xorbits/bge-m3",
        base_url=os.getenv("OPENAI_BASE_URL", "https://ms-ens-2fb01c9e-ff93.api-inference.modelscope.cn/v1"),
        api_key=os.getenv("OPENAI_API_KEY", "ms-14743223-8ddc-4989-8abf-e6eeb5b97d6e"),
    )

vec = em.embed_query("你好，世界")