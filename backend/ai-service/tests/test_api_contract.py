"""Day17：Pydantic 契约和 FastAPI 边界重构的最小验证。

只依赖 pydantic（不依赖 fastapi / Agent 运行时），验证：
- normalize_ai_response 把 Agent 内部 dict 适配成稳定 AIResponse 契约
- build_error_response 产出统一错误结构
- 流式 start / end / error 事件结构稳定
- 不同链路顶层字段一致，Java 不需要猜字段
"""
import json

from api.schemas import AIResponse
from api.response_adapter import (
    build_error_response,
    model_to_dict,
    normalize_ai_response,
    parse_stream_event,
    sse_event,
    stream_end_event,
    stream_error_event,
    stream_start_event,
)


# ---------------- 普通响应 ----------------

class TestNormalizeAIResponse:
    def test_chitchat_has_all_top_level_fields(self):
        result = {"answer": "你好呀", "sources": [], "task_type": "chitchat"}
        resp = normalize_ai_response(result, run_id="r1", trace_id="t1")
        assert resp.answer == "你好呀"
        assert resp.task_type == "chitchat"
        assert resp.sources == []
        assert resp.product_cards == []
        assert resp.confirm_card is None
        assert resp.cart_selection is None
        assert resp.cart_list is None
        assert resp.run_id == "r1"
        assert resp.trace_id == "t1"
        assert resp.error is False
        assert resp.error_code is None

    def test_shopping_keeps_product_cards(self):
        cards = [
            {
                "product_id": 101,
                "title": "Nike跑步鞋",
                "brand": "Nike",
                "base_price": 599.0,
                "image_url": "http://x/a.jpg",
                "rating": 4.8,
                "sub_category": "运动鞋",
                "reason": "轻量缓震",
            }
        ]
        resp = normalize_ai_response(
            {"answer": "为你推荐", "sources": [], "task_type": "shopping", "product_cards": cards},
            run_id="r2",
            trace_id="t2",
        )
        assert resp.task_type == "shopping"
        assert len(resp.product_cards) == 1
        assert resp.product_cards[0].product_id == 101
        assert resp.product_cards[0].title == "Nike跑步鞋"

    def test_cart_confirm_card(self):
        confirm = {"type": "confirm_card", "message": "确认删除第2个商品？", "buttons": []}
        resp = normalize_ai_response(
            {"answer": "请确认", "sources": [], "task_type": "cart", "confirm_card": confirm},
            run_id="r3",
            trace_id="t3",
        )
        assert resp.task_type == "cart"
        assert resp.confirm_card is not None
        assert resp.confirm_card.message == "确认删除第2个商品？"

    def test_cart_selection_and_list(self):
        selection = {"type": "cart_selection", "message": "选择要加购的商品", "items": []}
        resp = normalize_ai_response(
            {"answer": "", "sources": [], "task_type": "cart", "cart_selection": selection},
        )
        assert resp.cart_selection is not None
        assert resp.cart_selection.type == "cart_selection"

        listing = {"type": "cart_list", "message": "购物车里有：", "items": []}
        resp2 = normalize_ai_response(
            {"answer": "", "sources": [], "task_type": "cart", "cart_list": listing},
        )
        assert resp2.cart_list is not None
        assert resp2.cart_list.type == "cart_list"

    def test_error_flag_preserved(self):
        resp = normalize_ai_response(
            {"answer": "出错了", "sources": [], "task_type": "shopping", "error": True},
        )
        assert resp.error is True

    def test_empty_result_defaults_stable(self):
        resp = normalize_ai_response(None, run_id="r0", trace_id="t0")
        assert resp.answer == ""
        assert resp.task_type == "unknown"
        assert resp.sources == []
        assert resp.product_cards == []
        assert resp.run_id == "r0"
        assert resp.error is False


# ---------------- 错误响应 ----------------

class TestBuildErrorResponse:
    def test_error_structure_stable(self):
        resp = build_error_response("问答处理失败", run_id="r1", trace_id="t1")
        assert resp.error is True
        assert resp.error_code == "AI_INTERNAL_ERROR"
        assert resp.message == "问答处理失败"
        assert resp.run_id == "r1"
        assert resp.trace_id == "t1"
        assert resp.answer == ""
        assert resp.sources == []
        assert resp.product_cards == []

    def test_custom_error_code(self):
        resp = build_error_response("流式失败", error_code="AI_STREAM_ERROR")
        assert resp.error_code == "AI_STREAM_ERROR"


# ---------------- 流式事件 ----------------

class TestStreamEvents:
    def test_start_event_has_ids(self):
        ev = stream_start_event("r1", "t1")
        assert ev["type"] == "start"
        assert ev["run_id"] == "r1"
        assert ev["trace_id"] == "t1"

    def test_end_event_carries_full_response(self):
        resp = normalize_ai_response(
            {"answer": "hi", "sources": [], "task_type": "chitchat"}, run_id="r1", trace_id="t1"
        )
        ev = stream_end_event(resp)
        assert ev["type"] == "end"
        assert ev["response"] is not None
        assert ev["response"]["answer"] == "hi"
        assert ev["response"]["run_id"] == "r1"
        # end 事件字段与普通响应一致
        for key in (
            "answer", "sources", "task_type", "product_cards",
            "confirm_card", "cart_selection", "cart_list",
            "run_id", "trace_id", "error", "error_code", "message",
        ):
            assert key in ev["response"], f"end.response missing {key}"

    def test_error_event_stable(self):
        ev = stream_error_event("流式问答处理失败", "r1", "t1", "AI_STREAM_ERROR")
        assert ev["type"] == "error"
        assert ev["error"] is True
        assert ev["error_code"] == "AI_STREAM_ERROR"
        assert ev["message"] == "流式问答处理失败"
        assert ev["run_id"] == "r1"

    def test_sse_format(self):
        line = sse_event({"type": "token", "content": "你"})
        assert line.startswith("data: ")
        assert line.endswith("\n\n")
        payload = json.loads(line[len("data: "):].strip())
        assert payload["type"] == "token"
        assert payload["content"] == "你"

    def test_parse_stream_event_string_and_dict(self):
        assert parse_stream_event({"type": "token", "content": "a"}) == {"type": "token", "content": "a"}
        parsed = parse_stream_event('data: {"type": "routed", "task_type": "shopping"}\n\n')
        assert parsed["type"] == "routed"
        assert parsed["task_type"] == "shopping"


# ---------------- 契约一致性 ----------------

class TestContractConsistency:
    def test_airesponse_fields_complete(self):
        """AIResponse 顶层字段覆盖 Java 需要的全部字段，不靠 Map 猜。"""
        fields = set(AIResponse.__fields__.keys())
        required = {
            "answer", "sources", "task_type", "product_cards",
            "confirm_card", "cart_selection", "cart_list",
            "run_id", "trace_id", "error", "error_code", "message",
        }
        assert required.issubset(fields), f"missing: {required - fields}"