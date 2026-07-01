"""导购链测试：正常构建 + 无 key 降级。"""
from unittest.mock import MagicMock, patch


def test_shopping_chain_no_key_returns_none():
    with patch("core.llm.get_llm", return_value=None):
        from chains.shopping_chain import build_shopping_chain
        assert build_shopping_chain() is None


def test_shopping_chain_builds_when_key_present():
    with patch("core.llm.get_llm") as mock_llm:
        mock_llm.return_value = MagicMock()
        from chains.shopping_chain import build_shopping_chain
        chain = build_shopping_chain()
        assert chain is not None