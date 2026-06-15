import asyncio

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis

from app.config import get_settings
from app.handlers import admin, user
from app.logging import setup_logging
from app.middlewares.throttle import ThrottleMiddleware
from app.services.scheduler_service import build_scheduler


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    bot = Bot(settings.bot_token)
    redis = Redis.from_url(settings.redis_url)
    dp = Dispatcher(storage=RedisStorage(redis=redis))
    dp.message.middleware(ThrottleMiddleware())

    dp.include_router(admin.router)
    dp.include_router(user.router)

    # Ответы админов в темах обрабатывает reject_reason_or_forward в admin.py:
    # он сам вызывает forward_admin_reply для пересылки клиенту (без SkipHandler).

    scheduler = build_scheduler(bot)
    scheduler.start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
