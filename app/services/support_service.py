import logging
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models.entities import Application, User
from app.repositories.core import ApplicationRepository, SupportRepository, UserRepository


logger = logging.getLogger(__name__)


async def _forward_message(
    bot: Bot,
    chat_id: int,
    message: Message,
    prefix: str,
    message_thread_id: int | None = None,
) -> None:
    kwargs = dict(chat_id=chat_id)
    if message_thread_id is not None:
        kwargs["message_thread_id"] = message_thread_id

    original_text = message.text or message.caption or ""
    prefixed_text = f"{prefix}\n{original_text}" if original_text else prefix

    if message.text:
        await bot.send_message(**kwargs, text=prefixed_text)
    elif message.photo:
        await bot.send_photo(**kwargs, photo=message.photo[-1].file_id, caption=prefixed_text)
    elif message.video:
        await bot.send_video(**kwargs, video=message.video.file_id, caption=prefixed_text)
    elif message.document:
        await bot.send_document(**kwargs, document=message.document.file_id, caption=prefixed_text)
    elif message.audio:
        await bot.send_audio(**kwargs, audio=message.audio.file_id, caption=prefixed_text)
    elif message.voice:
        await bot.send_voice(**kwargs, voice=message.voice.file_id, caption=prefixed_text)
    elif message.video_note:
        await bot.send_video_note(**kwargs, video_note=message.video_note.file_id)
        if original_text:
            await bot.send_message(**kwargs, text=prefixed_text)
    elif message.animation:
        await bot.send_animation(**kwargs, animation=message.animation.file_id, caption=prefixed_text)
    else:
        await bot.send_message(**kwargs, text=prefixed_text)


async def forward_user_question(message: Message) -> None:
    settings = get_settings()
    async with SessionLocal() as db:
        user = await UserRepository(db).get_or_create(message.from_user.id, message.from_user.username)
        topic_id = await _resolve_or_create_topic_id(db, message, user.id, user.telegram_id)

    prefix = f"Вопрос от @{message.from_user.username or 'user'} ({message.from_user.id})"
    try:
        await _forward_message(
            message.bot, settings.admin_group_id, message, prefix,
            message_thread_id=topic_id,
        )
    except TelegramBadRequest as exc:
        reason = (exc.message or "").lower()
        if "thread" not in reason and "topic" not in reason:
            raise
        async with SessionLocal() as db:
            user = await UserRepository(db).get_or_create(message.from_user.id, message.from_user.username)
            topic_id = await _force_create_topic_id(db, message, user.id, user.telegram_id)
        await _forward_message(
            message.bot, settings.admin_group_id, message, prefix,
            message_thread_id=topic_id,
        )


async def forward_admin_reply(message: Message) -> None:
    if message.chat.id != get_settings().admin_group_id:
        return
    if not message.message_thread_id:
        return

    async with SessionLocal() as db:
        is_moderation = await db.scalar(
            select(Application.id).where(Application.moderation_topic_id == message.message_thread_id)
        )

        user = None
        if is_moderation:
            prefix = "Сообщение от администратора"
            app_user_id = await db.scalar(
                select(Application.user_id)
                .where(Application.id == is_moderation)
            )
            if app_user_id:
                user = await db.get(User, app_user_id)
        else:
            prefix = "Ответ поддержки"
            topic = await SupportRepository(db).get_by_topic(message.message_thread_id)
            if topic:
                user = await db.get(User, topic.user_id)
            else:
                logger.debug("forward_admin_reply: no support topic found")
                return

    if user:
        logger.info(
            "forward_admin_reply: forwarding reply to user",
            extra={"user_id": user.telegram_id, "thread_id": message.message_thread_id},
        )
        await _forward_message(message.bot, user.telegram_id, message, prefix)
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
