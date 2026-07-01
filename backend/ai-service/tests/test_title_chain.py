"""标题链测试：正常构建 + 无 key 降级。"""
from unittest.mock import MagicMock, patch


def test_title_chain_no_key_returns_none():
    with patch("core.llm.get_llm", return_value=None):
        from chains.title_chain import build_title_chain
        assert build_title_chain() is None


def test_title_chain_builds_when_key_present():
    with patch("core.llm.get_llm") as mock_llm:
        mock_llm.return_value = MagicMock()
        from chains.title_chain import build_title_chain
        chain = build_title_chain()
        assert chain is not None