"""测试 knowledge/agent.py 的实体抽取逻辑 —— 纯正则，无 LLM 依赖。"""
from __future__ import annotations

from knowledge.agent import (
    _extract_entities_from_query,
    _extract_entities_from_sources,
)


class TestExtractEntitiesFromQuery:
    """从用户 query 抽取候选知识实体：并列切分 + 停用词过滤。"""

    def test_and_separator_splits_two_entities(self):
        # 最经典 case：'X 和 Y 能一起用吗' → [X, Y]
        result = _extract_entities_from_query("烟酰胺和视黄醇能一起用吗")
        assert result == ["烟酰胺", "视黄醇"]

    def test_comma_separator_splits(self):
        result = _extract_entities_from_query("烟酰胺、视黄醇、透明质酸的功效")
        assert result == ["烟酰胺", "视黄醇", "透明质酸"]

    def test_or_separator_splits(self):
        result = _extract_entities_from_query("烟酰胺或水杨酸怎么选")
        assert "烟酰胺" in result
        assert "水杨酸" in result

    def test_english_entity(self):
        # 英文成分名也要能抽出来
        result = _extract_entities_from_query("VC 和 VE 能不能一起用")
        # "能不能"、"一起"、"用" 是停用词，"VC" "VE" 保留
        assert "VC" in result
        assert "VE" in result

    def test_stopwords_are_filtered(self):
        # 只有停用词 → 空
        result = _extract_entities_from_query("能不能一起用")
        assert result == []

    def test_dedup_preserves_order(self):
        # 重复实体只保留一次，保序
        result = _extract_entities_from_query("烟酰胺、烟酰胺和视黄醇")
        assert result == ["烟酰胺", "视黄醇"]

    def test_max_entities_limit(self):
        # 超过 max_entities 会被截断。用真实实体名，避免踩到"成分"是停用词的坑
        query = "烟酰胺、视黄醇、透明质酸、水杨酸、维生素C、维生素E的功效"
        result = _extract_entities_from_query(query, max_entities=3)
        assert len(result) == 3

    def test_empty_query(self):
        assert _extract_entities_from_query("") == []

    def test_pure_digits_not_entity(self):
        # 纯数字不算实体
        result = _extract_entities_from_query("200和300")
        assert result == []

    def test_single_entity_no_separator(self):
        # 没有分隔符时，取第一个非停用词 token
        result = _extract_entities_from_query("烟酰胺的功效原理")
        assert result == ["烟酰胺"]


class TestExtractEntitiesFromSources:
    """从 search_knowledge 返回的 sources.title 里抽 backup 实体。"""

    def test_extract_from_md_titles(self):
        sources = [
            {"title": "烟酰胺搭配禁忌.md", "score": 0.9},
            {"title": "视黄醇使用指南.md", "score": 0.8},
        ]
        result = _extract_entities_from_sources(sources)
        assert "烟酰胺" in result
        assert "视黄醇" in result

    def test_empty_sources(self):
        assert _extract_entities_from_sources([]) == []

    def test_stopwords_filtered(self):
        # title 里全是停用词 → 空
        sources = [{"title": "怎么用.md", "score": 0.5}]
        result = _extract_entities_from_sources(sources)
        assert result == []

    def test_max_entities_limit(self):
        sources = [{"title": f"实体{i}.md", "score": 0.9} for i in range(10)]
        result = _extract_entities_from_sources(sources, max_entities=3)
        assert len(result) == 3

    def test_title_without_extension(self):
        # 没扩展名也要能抽
        sources = [{"title": "透明质酸", "score": 0.7}]
        result = _extract_entities_from_sources(sources)
        assert result == ["透明质酸"]
