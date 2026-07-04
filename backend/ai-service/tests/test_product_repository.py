from decimal import Decimal
import asyncio

from shopping.models import ShoppingIntent
from shopping.orm_models import ProductORM
from shopping.product_repository import ProductRepository


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.added = []
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, statement):
        self.statement = statement
        return FakeResult(self.rows)

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


class FakeSessionFactory:
    def __init__(self, session):
        self.session = session

    def __call__(self):
        return self.session


def make_product(
    product_id=1,
    title="清爽防晒霜",
    description="适合油皮夏天使用",
    tags="清爽,油皮,防晒",
    sales_count=1200,
):
    return ProductORM(
        id=product_id,
        product_code=f"p{product_id}",
        category_id=10,
        title=title,
        brand="TestBrand",
        sub_category="防晒",
        base_price=Decimal("129.00"),
        image_url="http://example.com/a.jpg",
        description=description,
        tags=tags,
        rating=Decimal("4.80"),
        review_count=32,
        sales_count=sales_count,
        status=1,
        embedding_status=0,
    )


def test_search_products_maps_orm_row_to_candidate():
    async def run():
        session = FakeSession(rows=[(make_product(), "美妆护肤")])
        repository = ProductRepository(FakeSessionFactory(session))

        result = await repository.search_products(
            ShoppingIntent(is_shopping_request=True, category="防晒", budget_max=200)
        )

        assert len(result) == 1
        assert result[0].product_id == 1
        assert result[0].title == "清爽防晒霜"
        assert result[0].price == 129.0
        assert result[0].category == "美妆护肤"
        assert result[0].sub_category == "防晒"
        assert "匹配防晒" in result[0].reason
        assert "200元以内预算" in result[0].reason

    asyncio.run(run())


def test_search_products_reranks_soft_preference_matches():
    async def run():
        hot_generic = make_product(
            product_id=1,
            title="高销量防晒霜",
            description="日常通勤使用",
            tags="防晒",
            sales_count=9999,
        )
        matched = make_product(
            product_id=2,
            title="油皮清爽防晒霜",
            description="适合油皮夏天使用，肤感清爽",
            tags="防晒,油皮,清爽,夏天",
            sales_count=100,
        )
        session = FakeSession(rows=[(hot_generic, "美妆护肤"), (matched, "美妆护肤")])
        repository = ProductRepository(FakeSessionFactory(session))

        result = await repository.search_products(
            ShoppingIntent(
                is_shopping_request=True,
                category="防晒",
                scenario="夏天",
                preferences=["油皮", "清爽"],
                budget_max=200,
            )
        )

        assert [item.product_id for item in result[:2]] == [2, 1]
        assert "油皮" in result[0].reason or "清爽" in result[0].reason

    asyncio.run(run())


def test_log_recommendation_uses_orm_session():
    async def run():
        session = FakeSession()
        repository = ProductRepository(FakeSessionFactory(session))

        await repository.log_recommendation(
            user_id=7,
            session_id="c1",
            question="推荐防晒",
            product_ids=[1, 2],
            intent="shopping",
            recommend_reason="为你推荐",
        )

        assert session.committed is True
        assert len(session.added) == 1
        assert session.added[0].recommended_product_ids == [1, 2]

    asyncio.run(run())
