import logging
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models.entities import Application, User
from app.repositories.core import ApplicationRepository, SupportRepository, UserRepository


async def forward_user_question(message: Message) -> None:
    settings = get_settings()
    async with SessionLocal() as db:
        user = await UserRepository(db).get_or_create(message.from_user.id, message.from_user.username)
        topic_id = await _resolve_or_create_topic_id(db, message, user.id, user.telegram_id)

    text = f"Вопрос от @{message.from_user.username or 'user'} ({message.from_user.id}):\n{message.text}"
    try:
        await message.bot.send_message(
            chat_id=settings.admin_group_id,
            message_thread_id=topic_id,
            text=text,
        )
    except TelegramBadRequest as exc:
        reason = (exc.message or "").lower()
        if "thread" not in reason and "topic" not in reason:
            raise
        # topic may have been deleted/recreated manually in group settings
        async with SessionLocal() as db:
            user = await UserRepository(db).get_or_create(message.from_user.id, message.from_user.username)
            topic_id = await _force_create_topic_id(db, message, user.id, user.telegram_id)
        await message.bot.send_message(
            chat_id=settings.admin_group_id,
            message_thread_id=topic_id,
            text=text,
        )


async def forward_admin_reply(message: Message) -> None:
    logger = logging.getLogger(__name__)
    settings = get_settings()
    
    if message.chat.id != settings.admin_group_id:
        logger.debug("forward_admin_reply: not admin group", extra={"chat_id": message.chat.id})
        return
    
    if not message.message_thread_id:
        logger.debug("forward_admin_reply: no message_thread_id")
        return
    
    async with SessionLocal() as db:
        # КРИТИЧЕСКАЯ ПРОВЕРКА: это модерация или поддержка?
        is_moderation = await db.scalar(
            select(Application.id).where(Application.moderation_topic_id == message.message_thread_id)
        )
        
        if is_moderation:
            logger.info(
                "forward_admin_reply: SKIPPED moderation thread",
                extra={
                    "thread_id": message.message_thread_id,
                    "reason": "This is moderation, not support - reject_reason should handle it",
                }
            )
            # ОЧЕНЬ ВАЖНО: не обрабатываем модерацию здесь!
            # Оставляем it для reject_reason хендлера в admin.py
            return
        
        # Это не модерация, значит поддержка - продолжаем обработку
        logger.info(
            "forward_admin_reply: processing support reply",
            extra={"thread_id": message.message_thread_id}
        )
        
        topic = await SupportRepository(db).get_by_topic(message.message_thread_id)
        if not topic:
            logger.debug("forward_admin_reply: no support topic found", extra={"thread_id": message.message_thread_id})
            # Пытаемся найти по приложению (fallback)
            app_user_id = await db.scalar(
                select(Application.user_id)
                .where(Application.moderation_topic_id == message.message_thread_id)
                .order_by(Application.id.desc())
                .limit(1)
            )
            if not app_user_id:
                logger.debug("forward_admin_reply: no app_user_id found", extra={"thread_id": message.message_thread_id})
                return
            topic = await SupportRepository(db).get_or_create(app_user_id, message.message_thread_id)
            await db.commit()
        
        user = await db.get(User, topic.user_id)
    
    if user:
        logger.info(
            "forward_admin_reply: forwarding reply to user",
            extra={"user_id": user.telegram_id, "thread_id": message.message_thread_id}
        )
        await message.bot.send_message(user.telegram_id, f"Ответ поддержки:\n{message.text}")
    else:
        logger.warning("forward_admin_reply: user not found", extra={"thread_id": message.message_thread_id})


async def _resolve_or_create_topic_id(db, message: Message, user_id: int, user_telegram_id: int) -> int:
    repo = SupportRepository(db)
    app_repo = ApplicationRepository(db)

    topic = await repo.get_by_user(user_id)
    if topic:
        return topic.topic_id

    existing_topic_id = await app_repo.get_user_moderation_topic_id(user_id)
    if existing_topic_id:
        topic = await repo.set_topic_for_user(user_id, existing_topic_id)
        await db.commit()
        return topic.topic_id

    return await _force_create_topic_id(db, message, user_id, user_telegram_id)


async def _force_create_topic_id(db, message: Message, user_id: int, user_telegram_id: int) -> int:
    settings = get_settings()
    username = message.from_user.username if message.from_user else None
    created = await message.bot.create_forum_topic(
        chat_id=settings.admin_group_id,
        name=f"{username or 'tg'}_{user_telegram_id}",
    )
    topic = await SupportRepository(db).set_topic_for_user(user_id, created.message_thread_id)
    await db.commit()
    return topic.topic_id
