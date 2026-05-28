import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.db import SessionLocal
from app.handlers.user import WELCOME
from app.keyboards.common import start_keyboard
from app.models.entities import User
from app.repositories.core import SessionRepository
from app.services.wb_service import WBService

logger = logging.getLogger(__name__)


def build_scheduler(bot):
    scheduler = AsyncIOScheduler()

    @scheduler.scheduled_job("interval", minutes=5)
    async def check_timeouts() -> None:
        async with SessionLocal() as db:
            repo = SessionRepository(db)
            stale_30 = await repo.active_over_30()
            for s in stale_30:
                user = await db.get(User, s.user_id)
                if user:
                    await bot.send_message(user.telegram_id, "⏰ Пожалуйста, продолжите заполнение формы.")
                s.reminder_sent = True

            stale_60 = await repo.active_over_60()
            for s in stale_60:
                s.is_active = False
                user = await db.get(User, s.user_id)
                if user:
                    await bot.send_message(
                        user.telegram_id,
                        "⌛ Время ожидания истекло.\nДля продолжения начните заново.",
                    )
                    await bot.send_message(user.telegram_id, WELCOME, reply_markup=start_keyboard())
            await db.commit()

    @scheduler.scheduled_job("interval", minutes=30, next_run_time=datetime.now())
    async def sync_wb_products() -> None:
        try:
            async with SessionLocal() as db:
                total = await WBService(db).sync_products()
                logger.info("wb_products_synced", extra={"count": total})
        except Exception:
            logger.exception("wb_products_sync_failed")

    return scheduler
