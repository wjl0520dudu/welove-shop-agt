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


# ---- 用户相关 ORM 模型（原 Java API → 现 PG 直查）------------------------------


class UserORM(Base):
    """用户表（users）。"""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String(50))
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    password: Mapped[Optional[str]] = mapped_column(String(255))
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500))
    gender: Mapped[Optional[int]] = mapped_column(Integer)
    age_range: Mapped[Optional[str]] = mapped_column(String(20))
    skin_type: Mapped[Optional[str]] = mapped_column(String(50))
    # preference_tags 在 Java 通过 JacksonTypeHandler 存为 JSONB
    preference_tags: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    # profile JSONB：动态属性（concerns / allergens / budget_preference 等），
    # 由注册时预填 + 对话中偏好学习持续写入。
    # 迁移 SQL：ALTER TABLE users ADD COLUMN IF NOT EXISTS profile JSONB DEFAULT '{}';
    profile: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[Optional[int]] = mapped_column(Integer)
    create_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    update_time: Mapped[Optional[datetime]] = mapped_column(DateTime)


class UserFavoriteORM(Base):
    """用户收藏表（user_favorite）。"""
    __tablename__ = "user_favorite"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    product_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    create_time: Mapped[Optional[datetime]] = mapped_column(DateTime)


class UserBrowseHistoryORM(Base):
    """用户浏览历史表（user_browse_history）。"""
    __tablename__ = "user_browse_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    product_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    source: Mapped[Optional[str]] = mapped_column(String(50))
    duration_sec: Mapped[Optional[int]] = mapped_column(Integer)
    create_time: Mapped[Optional[datetime]] = mapped_column(DateTime)


class OrderORM(Base):
    """订单主表（orders）。"""
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    order_no: Mapped[Optional[str]] = mapped_column(String(50))
    status: Mapped[Optional[int]] = mapped_column(Integer)
    total_amount: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(10, 2))
    pay_amount: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(10, 2))
    freight_amount: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(10, 2))
    address_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    receiver_name: Mapped[Optional[str]] = mapped_column(String(50))
    receiver_phone: Mapped[Optional[str]] = mapped_column(String(20))
    receiver_address: Mapped[Optional[str]] = mapped_column(String(500))
    remark: Mapped[Optional[str]] = mapped_column(String(500))
    create_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    pay_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    delivery_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    receive_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    update_time: Mapped[Optional[datetime]] = mapped_column(DateTime)


class OrderItemORM(Base):
    """订单商品明细表（order_item）。"""
    __tablename__ = "order_item"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    product_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    product_title: Mapped[Optional[str]] = mapped_column(String(500))
    product_image: Mapped[Optional[str]] = mapped_column(String(500))
    sku_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    sku_properties: Mapped[Optional[str]] = mapped_column(String(500))
    price: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(10, 2))
    quantity: Mapped[Optional[int]] = mapped_column(Integer)
    total_amount: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(10, 2))


class ProductSkuORM(Base):
    """商品 SKU 表（product_sku）。"""
    __tablename__ = "product_sku"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    product_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    sku_code: Mapped[Optional[str]] = mapped_column(String(100))
    properties: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    price: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(10, 2))
    stock: Mapped[Optional[int]] = mapped_column(Integer)
    is_default: Mapped[Optional[bool]] = mapped_column(Boolean)
    create_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
