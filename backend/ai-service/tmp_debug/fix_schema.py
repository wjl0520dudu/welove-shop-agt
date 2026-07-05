path = r"G:\dev\welove-shop-agt\backend\ai-service\agents\schemas.py"
content = open(path, encoding="utf-8").read()

old = '''class IntentDecision(BaseModel):
    task_type: TaskType = Field(..., description="best route")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="confidence score")
    reason: str = Field("", description="reason for the decision")'''

new = '''class IntentDecision(BaseModel):
    task_type: TaskType = Field(
        ...,
        description="意图分类: shopping=搜索/推荐/比较具体商品, knowledge=了解知识/用法/成分/适合什么(即使提到商品名), chitchat=闲聊/问候/元问题(关于对话本身), unknown=无法判断",
    )
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="分类置信度")
    reason: str = Field("", description="分类理由")'''

content = content.replace(old, new)
open(path, "w", encoding="utf-8").write(content)
print("IntentDecision schema updated")