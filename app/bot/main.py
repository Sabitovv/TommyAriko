import asyncio

from aiogram import Bot, Dispatcher
from aiogram import F
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis

from app.config import get_settings
from app.handlers import admin, user
from app.logging import setup_logging
from app.middlewares.throttle import ThrottleMiddleware
from app.services.scheduler_service import build_scheduler
from app.services.support_service import forward_admin_reply


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    bot = Bot(settings.bot_token)
    redis = Redis.from_url(settings.redis_url)
    dp = Dispatcher(storage=RedisStorage(redis=redis))
    dp.message.middleware(ThrottleMiddleware())

    # ВАЖНО: Включить admin router ПЕРЕД регистрацией forward_admin_reply,
    # чтобы хендлеры модерации (reject_reason) проверялись первыми!
    # Это гарантирует, что _PendingReject() фильтр сработает до forward_admin_reply
    dp.include_router(admin.router)
    dp.include_router(user.router)
    
    # forward_admin_reply регистрируется ПОСЛЕ, но с более специфичными условиями
    # Она будет обрабатывать только поддержку, не модерацию
    dp.message.register(
        forward_admin_reply,
        F.chat.id == settings.admin_group_id,
        F.message_thread_id.is_not(None),
    )

    scheduler = build_scheduler(bot)
    scheduler.start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
