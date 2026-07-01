"""输出后处理测试。"""
from chains.postprocess import guard_empty, truncate


def test_guard_empty_keeps_nonempty():
    assert guard_empty("你好", "fallback") == "你好"


def test_guard_empty_fills_blank():
    assert guard_empty("", "兜底") == "兜底"
    assert guard_empty("   ", "兜底") == "兜底"


def test_truncate_short_unchanged():
    assert truncate("短文本", 100) == "短文本"


def test_truncate_long_cut():
    result = truncate("abcdefghijklmnopqrstuvwxyz", 10)
    assert len(result) == 11  # 10 字 + …
    assert result.endswith("…")