"""输出后处理：空回答兜底、超长截断。

chain 层的收尾处理，不碰 SSE 协议。
"""


def guard_empty(text: str, fallback: str) -> str:
    """空回答兜底，返回非空默认文案。"""
    stripped = (text or "").strip()
    return stripped if stripped else fallback


def truncate(text: str, max_chars: int) -> str:
    """超长回答截断，末尾加省略号。"""
    text = text or ""
    return text if len(text) <= max_chars else text[:max_chars] + "…"