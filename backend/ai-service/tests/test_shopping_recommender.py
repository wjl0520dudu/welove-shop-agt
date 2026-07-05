import asyncio

from shopping.models import ProductCandidate, ShoppingIntent
from shopping.recommender import ShoppingRecommender, shopping_state_to_result


class FakeChain:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def ainvoke(self, payload):
        self.calls.append(payload)
        return self.response




class FakeRepository:
    def __init__(self, products=None):
        self.products = products or []
        self.search_calls = []
        self.log_calls = []

    async def search_products(self, intent, limit=6):
        self.search_calls.append((intent, limit))
        return self.products

    async def log_recommendation(self, **kwargs):
        self.log_calls.append(kwargs)


def make_recommender(intent, products=None, answer="为你推荐这几款", fallback="请补充品类"):
    recommender = object.__new__(ShoppingRecommender)
    recommender.repository = FakeRepository(products)
    recommender.intent_chain = FakeChain(intent)
    recommender.answer_chain = FakeChain(answer)
    recommender.fallback_chain = FakeChain(fallback)
    recommender.graph = recommender._build_graph()
    return recommender


def test_recommend_with_products_builds_cards_and_logs():
    async def run():
        product = ProductCandidate(
            product_id=1,
            title="清爽防晒霜",
            brand="TestBrand",
            price=129,
            rating=4.8,
            review_count=30,
            sales_count=1200,
            category="美妆护肤",
            sub_category="防晒",
            tags="防晒,清爽,油皮",
        )
        recommender = make_recommender(
            ShoppingIntent(
                is_shopping_request=True,
                category="防晒",
                budget_max=200,
                preferences=["清爽"],
            ),
            products=[product],
        )

        state = await recommender.recommend("推荐200以内清爽防晒", user_id=7, session_id="s1")
        result = shopping_state_to_result(state)

        assert result["task_type"] == "shopping"
        assert result["answer"] == "为你推荐这几款"
        assert len(result["product_cards"]) == 1
        assert result["product_cards"][0]["reason"]
        assert recommender.repository.search_calls[0][0].category == "防晒"
        assert recommender.repository.log_calls[0]["product_ids"] == [1]

    asyncio.run(run())


def test_recommend_without_products_keeps_shopping_task_type():
    async def run():
        recommender = make_recommender(
            ShoppingIntent(is_shopping_request=True, category="防晒"),
            products=[],
            fallback="暂时没查到合适商品，可以换个预算或品牌看看。",
        )

        state = await recommender.recommend("推荐防晒")
        result = shopping_state_to_result(state)

        assert result["task_type"] == "shopping"
        assert result["product_cards"] == []
        assert "暂时没查到" in result["answer"]

    asyncio.run(run())


def test_non_shopping_request_uses_fallback_and_unknown_task_type():
    async def run():
        recommender = make_recommender(
            ShoppingIntent(
                is_shopping_request=False,
                need_followup=True,
                followup_question="你想看哪一类商品？",
            ),
            products=[ProductCandidate(product_id=1, title="不会被搜索")],
        )

        state = await recommender.recommend("讲个笑话")
        result = shopping_state_to_result(state)

        assert result["task_type"] == "unknown"
        assert result["answer"] == "你想看哪一类商品？"
        assert recommender.repository.search_calls == []

    asyncio.run(run())


def test_normalize_intent_accepts_structured_output_model():
    recommender = make_recommender(ShoppingIntent(is_shopping_request=True, category="耳机"))
    intent = recommender._normalize_intent(
        ShoppingIntent(is_shopping_request=True, category="防晒"),
        "推荐防晒",
    )

    assert intent.category == "防晒"
    assert intent.is_shopping_request is True
