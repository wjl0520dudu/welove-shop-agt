import sys
sys.path.insert(0, r"G:\dev\welove-shop-agt\backend\ai-service")

print("=== 1. 验证 state.py 字段 ===")
from agents.state import AssistantState
fields = list(AssistantState.__annotations__.keys())
print(f"字段数: {len(fields)}")
print(f"字段: {fields}")

print("\n=== 2. 验证 graph.py 导入 ===")
from assistant.graph import AssistantGraph
print("AssistantGraph 导入成功")

print("\n=== 3. 验证 nodes.py 导入 ===")
from assistant.nodes import make_nodes
print("make_nodes 导入成功")

print("\n=== 4. 构建 Graph ===")
graph = AssistantGraph(llm=None)
print("Graph 构建成功, 节点:", list(graph.graph.nodes.keys()))

print("\n=== 全部验证通过 ===")
