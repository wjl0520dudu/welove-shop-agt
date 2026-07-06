"""pgvector 商品搜索表 ORM 模型。

products_search 是 MySQL product 表的向量搜索副本，字段与 ProductORM 对应。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ProductSearchORM(Base):
    __tablename__ = "products_search"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    title: Mapped[str] = mapped_column(String(500))
    brand: Mapped[Optional[str]] = mapped_column(String(100))
    category_name: Mapped[Optional[str]] = mapped_column(String(50))
    sub_category: Mapped[Optional[str]] = mapped_column(String(50))
    base_price: Mapped[Optional[float]] = mapped_column(Float)
    image_url: Mapped[Optional[str]] = mapped_column(String(500))
    rating: Mapped[Optional[float]] = mapped_column(Float)
    review_count: Mapped[Optional[int]] = mapped_column(Integer)
    sales_count: Mapped[Optional[int]] = mapped_column(Integer)
    tags: Mapped[Optional[str]] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[Optional[int]] = mapped_column(Integer, default=1)

    embedding: Mapped[list[float]] = mapped_column(Vector(1536))

    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=datetime.utcnow
    )
