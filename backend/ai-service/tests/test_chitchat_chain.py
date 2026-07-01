"""闲聊链测试：正常构建 + 无 key 降级。"""
from unittest.mock import MagicMock, patch


def test_chitchat_chain_no_key_returns_none():
    """无 API key 时 build 返回 None，调用方走降级。"""
    with patch("core.llm.get_llm", return_value=None):
        from chains.chitchat_chain import build_chitchat_chain
        assert build_chitchat_chain() is None


def test_chitchat_chain_builds_when_key_present():
    """有 key 时 build 返回一条 LCEL 链（不是 None）。"""
    with patch("core.llm.get_llm") as mock_llm:
        mock_llm.return_value = MagicMock()
        from chains.chitchat_chain import build_chitchat_chain
        chain = build_chitchat_chain()
        assert chain is not None