import asyncio

from api.schemas import ChatRequest


def test_shopping_recommend_without_llm_returns_stable_error(monkeypatch):
    async def run():
        from api import shopping_routes

        monkeypatch.setattr(shopping_routes, "get_llm", lambda: None)

        response = await shopping_routes.recommend(ChatRequest(question="推荐一款防晒"))

        assert response.task_type == "shopping"
        assert response.error is True
        assert response.error_code == "AI_LLM_NOT_CONFIGURED"
        assert response.product_cards == []

    asyncio.run(run())
