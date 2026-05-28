from enum import StrEnum

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class ApplicationStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NEEDS_CORRECTION = "NEEDS_CORRECTION"


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    full_name: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(20))
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)


class Store(Base, TimestampMixin):
    __tablename__ = "stores"
    id: Mapped[int] = mapped_column(primary_key=True)
    external_store_id: Mapped[str] = mapped_column(String(128), unique=True)
    title: Mapped[str] = mapped_column(String(255))


class Product(Base, TimestampMixin):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("article", "store_id", name="uq_article_store"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"))
    category: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    article: Mapped[str] = mapped_column(String(64), index=True)
    wb_link: Mapped[str | None] = mapped_column(String(500))
    warranty_months: Mapped[int] = mapped_column(Integer, default=12)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    store: Mapped[Store] = relationship()


class Application(Base, TimestampMixin):
    __tablename__ = "applications"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    customer_full_name: Mapped[str] = mapped_column(String(255))
    city: Mapped[str] = mapped_column(String(128))
    phone: Mapped[str] = mapped_column(String(20))
    article: Mapped[str] = mapped_column(String(64))
    screenshot_file_id: Mapped[str] = mapped_column(String(255))
    screenshot_path: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(32), default=ApplicationStatus.PENDING)
    corrections_count: Mapped[int] = mapped_column(Integer, default=0)
    moderation_topic_id: Mapped[int | None] = mapped_column(BigInteger)
    moderation_message_id: Mapped[int | None] = mapped_column(BigInteger)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    correction_comment: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship()
    product: Mapped[Product] = relationship()


class SupportTopic(Base, TimestampMixin):
    __tablename__ = "support_topics"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    topic_id: Mapped[int] = mapped_column(BigInteger, unique=True)


class SupportMessage(Base, TimestampMixin):
    __tablename__ = "support_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    support_topic_id: Mapped[int] = mapped_column(ForeignKey("support_topics.id", ondelete="CASCADE"))
    from_admin: Mapped[bool] = mapped_column(Boolean)
    text: Mapped[str] = mapped_column(Text)


class Session(Base, TimestampMixin):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    state: Mapped[str] = mapped_column(String(128))
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped[User] = relationship()


class Admin(Base, TimestampMixin):
    __tablename__ = "admins"
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
