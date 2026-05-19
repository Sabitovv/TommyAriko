from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.types import FSInputFile

from app.config import get_settings
from app.keyboards.common import moderation_keyboard
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
    msg = await bot.send_photo(
        chat_id=settings.admin_group_id,
        message_thread_id=app.moderation_topic_id,
        photo=app.screenshot_file_id,
        caption=caption,
        reply_markup=moderation_keyboard(app.id),
    )
    app.moderation_message_id = msg.message_id


async def send_approved(bot: Bot, app: Application) -> None:
    pdf_path = PDFService().build_warranty_pdf(app)
    await bot.send_message(app.user.telegram_id, "✅ Ваша гарантия успешно активирована.")
    await bot.send_document(app.user.telegram_id, document=FSInputFile(pdf_path))


async def send_rejected(bot: Bot, user_telegram_id: int, reason: str) -> None:
    await bot.send_message(user_telegram_id, f"❌ В активации гарантии отказано.\n\nПричина:\n{reason}")


async def send_to_correction(bot: Bot, user_telegram_id: int, comment: str) -> None:
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✏ Исправить данные", callback_data="edit_application")]]
    )
    await bot.send_message(
        user_telegram_id,
        f"Требуется уточнение по заявке.\n\nКомментарий администратора:\n{comment}",
        reply_markup=kb,
    )
