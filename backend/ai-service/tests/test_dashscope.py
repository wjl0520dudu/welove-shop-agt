import dashscope
from http import HTTPStatus

# 1. 填入你自己的百炼API Key
dashscope.api_key = "sk-ws-H.RXEMIIM.3TxO.MEQCIFAloE-SL77yOwFE1H0NIvCm9IODj8b6QIJ4cM7ehjYhAiAZqSJykdx9Ey0ZSJYTYDel-RMo07Hmi4730c0R3o3y2w"

input_texts = "帅啊啊啊啊啊啊啊啊啊啊1234567890"

resp = dashscope.TextEmbedding.call(
    model="text-embedding-v4",
    input=input_texts,
    # 关键：开启同时返回稠密+稀疏向量
    parameters={"output_type": "dense&sparse"}
)

# 判断请求是否成功
if resp.status_code == HTTPStatus.OK:
    print("稠密向量：", resp.output.embeddings[0]['dense_embedding'])
    print("稀疏向量：", resp.output.embeddings[0]['sparse_embedding'])
else:
    print("调用失败：", resp.code, resp.message)