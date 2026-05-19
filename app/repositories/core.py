from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Application, ApplicationStatus, Product, Session, Store, SupportTopic, User


class UserRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create(self, telegram_id: int, username: str | None) -> User:
        user = await self.db.scalar(select(User).where(User.telegram_id == telegram_id))
        if user:
            return user
        user = User(telegram_id=telegram_id, username=username)
        self.db.add(user)
        await self.db.flush()
        return user


class ProductRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_deduped_products(self) -> list[Product]:
        stmt = (
            select(Product)
            .where(Product.is_active.is_(True))
            .order_by(Product.name)
        )
        rows = (await self.db.scalars(stmt)).all()
        unique: dict[str, Product] = {}
        for p in rows:
            unique.setdefault(p.name.lower().strip(), p)
        return list(unique.values())

    async def get_by_id(self, product_id: int) -> Product | None:
        return await self.db.get(Product, product_id)

    async def valid_article(self, product_name: str, article: str) -> Product | None:
        return await self.db.scalar(
            select(Product).where(Product.name == product_name, Product.article == article, Product.is_active.is_(True))
        )

    async def valid_article_by_category(self, category: str, article: str) -> Product | None:
        return await self.db.scalar(
            select(Product).where(
                Product.category == category,
                Product.article == article,
                Product.is_active.is_(True),
            )
        )


class ApplicationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def next_number(self) -> str:
        year = datetime.now(timezone.utc).year
        count = await self.db.scalar(select(func.count(Application.id)))
        seq = (count or 0) + 1
        return f"GT-{year}-{seq:06d}"

    async def create(self, **kwargs) -> Application:
        obj = Application(**kwargs)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def latest_by_user(self, user_id: int) -> Application | None:
        return await self.db.scalar(
            select(Application)
            .options(selectinload(Application.user), selectinload(Application.product))
            .where(Application.user_id == user_id)
            .order_by(Application.id.desc())
            .limit(1)
        )

    async def get_user_moderation_topic_id(self, user_id: int) -> int | None:
        return await self.db.scalar(
            select(Application.moderation_topic_id)
            .where(
                Application.user_id == user_id,
                Application.moderation_topic_id.is_not(None),
            )
            .order_by(Application.id.desc())
            .limit(1)
        )

    async def latest_needs_correction_by_user(self, user_id: int) -> Application | None:
        return await self.db.scalar(
            select(Application)
            .options(selectinload(Application.user), selectinload(Application.product))
            .where(
                Application.user_id == user_id,
                Application.status == ApplicationStatus.NEEDS_CORRECTION,
            )
            .order_by(Application.id.desc())
            .limit(1)
        )

    async def update_from_user_form(
        self,
        app: Application,
        *,
        full_name: str,
        city: str,
        phone: str,
        product_id: int,
        article: str,
        screenshot_file_id: str,
        screenshot_path: str,
    ) -> Application:
        app.customer_full_name = full_name
        app.city = city
        app.phone = phone
        app.product_id = product_id
        app.article = article
        app.screenshot_file_id = screenshot_file_id
        app.screenshot_path = screenshot_path
        app.status = ApplicationStatus.PENDING
        app.correction_comment = None
        return app

    async def set_status(self, app_id: int, status: ApplicationStatus, reason: str | None = None) -> None:
        await self.db.execute(
            update(Application)
            .where(Application.id == app_id)
            .values(status=status, rejection_reason=reason)
        )

    async def get(self, app_id: int) -> Application | None:
        return await self.db.scalar(
            select(Application)
            .options(selectinload(Application.user), selectinload(Application.product))
            .where(Application.id == app_id)
        )

    async def mark_correction_requested(self, app_id: int, comment: str) -> Application | None:
        app = await self.get(app_id)
        if not app:
            return None
        app.status = ApplicationStatus.NEEDS_CORRECTION
        app.corrections_count += 1
        app.correction_comment = comment
        return app


class SessionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def touch(self, user_id: int, state: str) -> None:
        existing = await self.db.scalar(select(Session).where(Session.user_id == user_id, Session.is_active.is_(True)))
        if existing:
            existing.state = state
            existing.updated_at = datetime.now(timezone.utc)
            existing.reminder_sent = False
            return
        self.db.add(Session(user_id=user_id, state=state))

    async def active_over_30(self) -> list[Session]:
        border = datetime.now(timezone.utc) - timedelta(minutes=30)
        return (
            await self.db.scalars(
                select(Session).where(
                    Session.is_active.is_(True),
                    Session.updated_at < border,
                    Session.reminder_sent.is_(False),
                    Session.state.like("FORM_%"),
                )
            )
        ).all()

    async def active_over_60(self) -> list[Session]:
        border = datetime.now(timezone.utc) - timedelta(minutes=60)
        return (
            await self.db.scalars(
                select(Session).where(
                    Session.is_active.is_(True),
                    Session.updated_at < border,
                    Session.state.like("FORM_%"),
                )
            )
        ).all()


class SupportRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_topic(self, topic_id: int) -> SupportTopic | None:
        return await self.db.scalar(select(SupportTopic).where(SupportTopic.topic_id == topic_id))

    async def get_by_user(self, user_id: int) -> SupportTopic | None:
        return await self.db.scalar(select(SupportTopic).where(SupportTopic.user_id == user_id))

    async def get_or_create(self, user_id: int, topic_id: int) -> SupportTopic:
        topic = await self.db.scalar(select(SupportTopic).where(SupportTopic.user_id == user_id))
        if topic:
            return topic
        topic = SupportTopic(user_id=user_id, topic_id=topic_id)
        self.db.add(topic)
        await self.db.flush()
        return topic

    async def set_topic_for_user(self, user_id: int, topic_id: int) -> SupportTopic:
        topic = await self.db.scalar(select(SupportTopic).where(SupportTopic.user_id == user_id))
        if topic:
            topic.topic_id = topic_id
            await self.db.flush()
            return topic
        topic = SupportTopic(user_id=user_id, topic_id=topic_id)
        self.db.add(topic)
        await self.db.flush()
        return topic


class StoreRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create(self, external_store_id: str, title: str) -> Store:
        obj = await self.db.scalar(select(Store).where(Store.external_store_id == external_store_id))
        if obj:
            return obj
        obj = Store(external_store_id=external_store_id, title=title)
        self.db.add(obj)
        await self.db.flush()
        return obj
