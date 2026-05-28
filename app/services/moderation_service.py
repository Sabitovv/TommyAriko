import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile

from app.config import get_settings
from app.keyboards.common import edit_fields_keyboard, moderation_keyboard, start_keyboard
from app.models.entities import Application
from app.services.pdf_service import PDFService


async def publish_application_for_moderation(bot: Bot, app: Application) -> None:
    settings = get_settings()
    if not app.moderation_topic_id:
        topic = await bot.create_forum_topic(
            chat_id=settings.admin_group_id,
            name=f"{app.user.username or 'user'}_{app.user.telegram_id}",
        )
        app.moderation_topic_id = topic.message_thread_id

    caption = (
        f"Заявка: {app.number}\n"
        f"Статус: {app.status}\n"
        f"ФИО: {app.customer_full_name}\n"
        f"Город: {app.city}\n"
        f"Телефон: {app.phone}\n"
        f"Товар: {app.product.name}\n"
        f"Артикул: {app.article}\n"
        f"WB: {app.product.wb_link}\n"
        f"Исправлений: {app.corrections_count}"
    )
    try:
        msg = await bot.send_photo(
            chat_id=settings.admin_group_id,
            message_thread_id=app.moderation_topic_id,
            photo=app.screenshot_file_id,
            caption=caption,
            reply_markup=moderation_keyboard(app.id),
        )
    except TelegramBadRequest as exc:
        reason = (exc.message or "").lower()
        if "thread" not in reason and "topic" not in reason:
            raise
        topic = await bot.create_forum_topic(
            chat_id=settings.admin_group_id,
            name=f"{app.user.username or 'user'}_{app.user.telegram_id}",
        )
        app.moderation_topic_id = topic.message_thread_id
        msg = await bot.send_photo(
            chat_id=settings.admin_group_id,
            message_thread_id=app.moderation_topic_id,
            photo=app.screenshot_file_id,
            caption=caption,
            reply_markup=moderation_keyboard(app.id),
        )
    app.moderation_message_id = msg.message_id


async def send_approved(bot: Bot, app: Application) -> None:
    logger = logging.getLogger(__name__)
    try:
        pdf_path = PDFService().build_warranty_pdf(app)
        await bot.send_message(app.user.telegram_id, "✅ Ваша гарантия успешно активирована.")
        await bot.send_document(app.user.telegram_id, document=FSInputFile(pdf_path))
        await bot.send_message(
            app.user.telegram_id,
            "Можно начать новую активацию или задать вопрос в поддержку.",
            reply_markup=start_keyboard(),
        )
    except Exception:
        logger.exception("send_approved_failed", extra={"app_id": app.id, "user_id": app.user.telegram_id if app.user else None})


async def send_rejected(bot: Bot, user_telegram_id: int, reason: str) -> None:
    logger = logging.getLogger(__name__)
    try:
        await bot.send_message(user_telegram_id, f"❌ В активации гарантии отказано.\n\nПричина:\n{reason}")
    except Exception:
        logger.exception("send_rejected_failed", extra={"user_id": user_telegram_id})


async def send_to_correction(bot: Bot, user_telegram_id: int, comment: str) -> None:
    logger = logging.getLogger(__name__)
    try:
        await bot.send_message(
            user_telegram_id,
            f"Требуется уточнение по заявке.\n\nКомментарий администратора:\n{comment}",
        )
        await bot.send_message(
            user_telegram_id,
            "Выберите поле для исправления:",
            reply_markup=edit_fields_keyboard(prefix="corr_edit"),
        )
    except Exception:
        logger.exception("send_to_correction_failed", extra={"user_id": user_telegram_id})


async def update_moderation_message(bot: Bot, app: Application, caption: str | None = None) -> None:
    logger = logging.getLogger(__name__)
    if not app.moderation_message_id:
        logger.warning("update_moderation_message: moderation_message_id is None", extra={"app_id": app.id})
        return
    try:
        if caption:
            await bot.edit_message_caption(
                chat_id=get_settings().admin_group_id,
                message_id=app.moderation_message_id,
                caption=caption,
                reply_markup=None,
            )
        else:
            await bot.edit_message_reply_markup(
                chat_id=get_settings().admin_group_id,
                message_id=app.moderation_message_id,
                reply_markup=None,
            )
        logger.info("update_moderation_message: done", extra={"app_id": app.id, "msg_id": app.moderation_message_id})
    except TelegramBadRequest as exc:
        logger.warning("update_moderation_message: TelegramBadRequest", extra={"app_id": app.id, "msg_id": app.moderation_message_id, "exc": str(exc)})
