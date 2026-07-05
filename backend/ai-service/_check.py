import sys
sys.path.insert(0, r"G:\dev\welove-shop-agt\backend\ai-service")

from agents.state import AssistantState
from assistant.graph import AssistantGraph
from assistant.nodes import make_nodes

fields = list(AssistantState.__annotations__.keys())
print("AssistantState 字段:", fields)
print("字段总数:", len(fields))

graph = AssistantGraph(llm=None)
print("Graph 节点:", list(graph.graph.nodes.keys()))
print("全部验证通过")
