from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, DECIMAL, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class CategoryORM(Base):
    __tablename__ = "category"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    description: Mapped[Optional[str]] = mapped_column(String(500))

    products: Mapped[list["ProductORM"]] = relationship(back_populates="category")


class ProductORM(Base):
    __tablename__ = "product"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    product_code: Mapped[str] = mapped_column(String(50))
    category_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("category.id"))
    title: Mapped[str] = mapped_column(String(500))
    brand: Mapped[Optional[str]] = mapped_column(String(100))
    sub_category: Mapped[Optional[str]] = mapped_column(String(50))
    base_price: Mapped[Decimal] = mapped_column(DECIMAL(10, 2))
    image_url: Mapped[Optional[str]] = mapped_column(String(500))
    description: Mapped[Optional[str]] = mapped_column(Text)
    tags: Mapped[Optional[str]] = mapped_column(String(1000))
    rating: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(3, 2))
    review_count: Mapped[Optional[int]] = mapped_column(Integer)
    sales_count: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[Optional[int]] = mapped_column(Integer)
    embedding_status: Mapped[Optional[int]] = mapped_column(Integer)
    create_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    update_time: Mapped[Optional[datetime]] = mapped_column(DateTime)

    category: Mapped[CategoryORM] = relationship(back_populates="products")


class RecommendationLogORM(Base):
    __tablename__ = "recommendation_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    session_id: Mapped[Optional[str]] = mapped_column(String(64))
    message_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    query: Mapped[Optional[str]] = mapped_column(Text)
    intent: Mapped[Optional[str]] = mapped_column(String(50))
    recommended_product_ids: Mapped[Optional[list[int]]] = mapped_column(JSON)
    recommend_reason: Mapped[Optional[str]] = mapped_column(Text)
    agent_reasoning: Mapped[Optional[str]] = mapped_column(Text)
    # PG 里 user_clicked 已从 SMALLINT 改为 BOOLEAN（Java 端 Boolean 类型对应）。
    # Python ORM 同步类型，避免 SQLAlchemy 序列化时用 int 触发 PG 类型冲突。
    user_clicked: Mapped[Optional[bool]] = mapped_column(Boolean)
    user_feedback: Mapped[Optional[int]] = mapped_column(Integer)
    create_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
