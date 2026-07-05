import sys
sys.path.insert(0, r"G:\dev\welove-shop-agt\backend\ai-service")

print("=== 导入测试 ===")
from assistant.graph import AssistantGraph
from agents.runtime import checkpointer
from agents.state import AssistantState
from assistant.nodes import make_nodes
print("全部导入成功")

print(f"checkpointer: {type(checkpointer).__name__}")
print(f"AssistantState 字段: {list(AssistantState.__annotations__.keys())}")

print()
print("=== Graph构建测试 ===")
graph = AssistantGraph(llm=None)
print(f"Graph节点: {list(graph.graph.nodes.keys())}")
print("Graph构建成功")
