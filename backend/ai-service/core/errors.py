"""统一错误码定义。

契约：错误码是稳定字符串常量，Java 侧和前端可以据此做本地化文案 / 降级策略。
不要在业务代码里硬编码字符串，用这里的常量。

## 使用方式

    from core.errors import ErrorCode
    return {"error": True, "error_code": ErrorCode.LLM_TIMEOUT, "message": "..."}

## 命名规则

`{域}_{原因}`，全大写下划线。域：AI / LLM / DB / JAVA / CART / KNOWLEDGE / SHOPPING / AUTH。
"""
from __future__ import annotations


class ErrorCode:
    # ── LLM / 模型层 ─────────────────────────────
    LLM_NOT_CONFIGURED = "AI_LLM_NOT_CONFIGURED"
    LLM_TIMEOUT = "AI_LLM_TIMEOUT"
    LLM_RATE_LIMIT = "AI_LLM_RATE_LIMIT"
    LLM_ERROR = "AI_LLM_ERROR"

    # ── 主图 / 编排层 ─────────────────────────────
    ASSISTANT_ERROR = "AI_ASSISTANT_ERROR"
    ROUTING_FAILED = "AI_ROUTING_FAILED"

    # ── 各子 agent ───────────────────────────────
    SHOPPING_ERROR = "AI_SHOPPING_ERROR"
    KNOWLEDGE_ERROR = "AI_RAG_ERROR"
    CHITCHAT_ERROR = "AI_CHITCHAT_ERROR"

    # ── 数据层 ───────────────────────────────────
    DB_UNAVAILABLE = "AI_DB_UNAVAILABLE"
    VECTOR_STORE_UNAVAILABLE = "AI_VECTOR_STORE_UNAVAILABLE"

    # ── 外部依赖 ─────────────────────────────────
    JAVA_API_UNAVAILABLE = "AI_JAVA_API_UNAVAILABLE"
    JAVA_API_ERROR = "AI_JAVA_API_ERROR"

    # ── 用户/权限 ─────────────────────────────────
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    FORBIDDEN = "FORBIDDEN"

    # ── 请求参数 ─────────────────────────────────
    BAD_REQUEST = "BAD_REQUEST"
    RATE_LIMITED = "RATE_LIMITED"


# 供 Java 侧参考的错误码 → 用户可见文案。
# ai-service 不返回本地化文案（那是前端/网关的活），只保证 error_code 稳定。
USER_MESSAGE_HINT: dict[str, str] = {
    ErrorCode.LLM_NOT_CONFIGURED: "AI 服务尚未配置，暂不可用",
    ErrorCode.LLM_TIMEOUT: "AI 响应超时，请稍后重试",
    ErrorCode.LLM_RATE_LIMIT: "当前使用人数较多，请稍后重试",
    ErrorCode.LLM_ERROR: "AI 服务出错，请稍后重试",
    ErrorCode.ASSISTANT_ERROR: "AI 助手暂时不可用",
    ErrorCode.ROUTING_FAILED: "无法理解你的请求，请换个说法",
    ErrorCode.SHOPPING_ERROR: "商品搜索暂时不可用，请稍后重试",
    ErrorCode.KNOWLEDGE_ERROR: "知识检索暂时不可用，请稍后重试",
    ErrorCode.CHITCHAT_ERROR: "闲聊回复失败，请稍后重试",
    ErrorCode.DB_UNAVAILABLE: "数据服务暂时不可用",
    ErrorCode.VECTOR_STORE_UNAVAILABLE: "向量检索暂时不可用",
    ErrorCode.JAVA_API_UNAVAILABLE: "业务服务暂时不可用",
    ErrorCode.JAVA_API_ERROR: "业务服务返回错误",
    ErrorCode.LOGIN_REQUIRED: "请登录后使用此功能",
    ErrorCode.FORBIDDEN: "无权访问",
    ErrorCode.BAD_REQUEST: "请求参数有误",
    ErrorCode.RATE_LIMITED: "请求过于频繁，请稍后重试",
}
