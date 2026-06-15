import csv
import logging
from pathlib import Path
from tempfile import NamedTemporaryFile

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from app.config import get_settings
from app.db import SessionLocal
from app.models.entities import ApplicationStatus
from app.repositories.core import ApplicationRepository
from app.services.moderation_service import update_moderation_message, send_approved, send_rejected, send_to_correction
from app.services.support_service import forward_admin_reply


logger = logging.getLogger(__name__)

_pending_corrections: dict[int, int] = {}  # thread_id -> app_id


router = Router()


REPORT_HEADERS = [
    "имя",
    "номер телефона",
    "город",
    "что приобрели",
    "артикул товара",
    "ссылка на скриншот отзыв",
    "Дата оставления отзыва",
]


async def _remove_inline_keyboard(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass


def _screenshot_link(topic_id: int | None, message_id: int | None) -> str:
    if not message_id:
        return ""
    internal_chat_id = str(abs(get_settings().admin_group_id))
    if internal_chat_id.startswith("100"):
        internal_chat_id = internal_chat_id[3:]
    if topic_id:
        return f"https://t.me/c/{internal_chat_id}/{topic_id}/{message_id}"
    return f"https://t.me/c/{internal_chat_id}/{message_id}"


async def _is_report_allowed(message: Message) -> bool:
    settings = get_settings()
    if not message.from_user:
        return False
    try:
        member = await message.bot.get_chat_member(settings.admin_group_id, message.from_user.id)
    except TelegramBadRequest:
        return False
    return member.status in {"creator", "administrator"}


def _csv_value(value: object) -> str:
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


@router.message(Command("data", "report", "csv"))
async def send_applications_report(message: Message) -> None:
    if not await _is_report_allowed(message):
        await message.answer("Команда доступна только администраторам.")
        return

    async with SessionLocal() as db:
        applications = await ApplicationRepository(db).list_for_report()

    if not applications:
        await message.answer("Заявок для отчёта пока нет.")
        return

    with NamedTemporaryFile("w", encoding="utf-8-sig", newline="", suffix=".csv", delete=False) as tmp:
        path = Path(tmp.name)
        writer = csv.DictWriter(tmp, fieldnames=REPORT_HEADERS)
        writer.writeheader()
        for app in applications:
            writer.writerow(
                {
                    "имя": _csv_value(app.customer_full_name),
                    "номер телефона": _csv_value(app.phone),
                    "город": _csv_value(app.city),
                    "что приобрели": _csv_value(app.product.name if app.product else ""),
                    "артикул товара": _csv_value(app.article),
                    "ссылка на скриншот отзыв": _csv_value(_screenshot_link(
                        app.moderation_topic_id,
                        app.moderation_message_id,
                    )),
                    "Дата оставления отзыва": _csv_value(
                        app.created_at.strftime("%Y-%m-%d %H:%M:%S") if app.created_at else ""
                    ),
                }
            )

    try:
        await message.answer_document(
            FSInputFile(path, filename="applications_report.csv"),
            caption=f"Отчёт по заявкам: {len(applications)}",
        )
    finally:
        path.unlink(missing_ok=True)


@router.callback_query(F.data.startswith("mod:approve:"))
async def approve(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    app_id = int(callback.data.split(":")[-1])
    async with SessionLocal() as db:
        repo = ApplicationRepository(db)
        app = await repo.get(app_id)
        if app and app.status not in (ApplicationStatus.PENDING, ApplicationStatus.NEEDS_CORRECTION):
            await _remove_inline_keyboard(callback)
            await callback.answer("Заявка уже обработана", show_alert=True)
            return
        await repo.set_status(app_id, ApplicationStatus.APPROVED)
        app = await repo.get(app_id)
        await db.commit()
    if app:
        await send_approved(callback.bot, app)
        await update_moderation_message(callback.bot, app, f"✅ Одобрено\nЗаявка: {app.number}")
    await callback.answer("Одобрено")


@router.callback_query(F.data.startswith("mod:reject:"))
async def reject_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    app_id = int(callback.data.split(":")[-1])
    logger.info("reject: callback received", extra={"app_id": app_id, "callback_chat_id": callback.message.chat.id})

    try:
        async with SessionLocal() as db:
            repo = ApplicationRepository(db)
            app = await repo.get(app_id)
            if not app:
                logger.error("reject: app not found", extra={"app_id": app_id})
                await _remove_inline_keyboard(callback)
                await callback.answer("Заявка не найдена", show_alert=True)
                return
            if app.status not in (ApplicationStatus.PENDING, ApplicationStatus.NEEDS_CORRECTION):
                logger.warning("reject: app already processed", extra={"app_id": app_id, "status": app.status})
                await _remove_inline_keyboard(callback)
                await callback.answer("Заявка уже обработана", show_alert=True)
                return

            await repo.set_status(app_id, ApplicationStatus.REJECTED)
            app = await repo.get(app_id)
            user_telegram_id = app.user.telegram_id if app and app.user else None
            await db.commit()

        if user_telegram_id:
            await send_rejected(callback.bot, user_telegram_id)
        if app:
            await update_moderation_message(callback.bot, app, f"❌ Отклонено\nЗаявка: {app.number}")
        await callback.bot.send_message(
            chat_id=callback.message.chat.id,
            message_thread_id=callback.message.message_thread_id,
            text="✅ Заявка отклонена",
        )
        await callback.answer("Отклонено")
    except Exception:
        logger.exception("reject: failed", extra={"app_id": app_id})
        await callback.answer("❌ Произошла ошибка. Повторите попытку.", show_alert=True)


@router.message(F.chat.id == get_settings().admin_group_id, F.message_thread_id.is_not(None))
async def reject_reason_or_forward(message: Message) -> None:
    """
    Обработчик для сообщений в темах админ-группы.
    Проверяет _pending_corrections. Если исправление не ожидается —
    напрямую вызывает forward_admin_reply, чтобы переслать ответ клиенту.
    """
    logger.info("admin_message: called", extra={"thread_id": message.message_thread_id})
    tid = message.message_thread_id
    reason_text = message.text or message.caption or ""

    # --- CORRECTION ---
    if tid in _pending_corrections:
        if not reason_text:
            await message.bot.send_message(
                chat_id=message.chat.id,
                message_thread_id=tid,
                text="Пожалуйста, напишите комментарий к исправлению текстом или добавьте подпись к медиа.",
            )
            return
        app_id = _pending_corrections.pop(tid, None)
        logger.info("admin_message: handling correction", extra={"thread_id": tid, "app_id": app_id})
        if app_id is None:
            return
        try:
            async with SessionLocal() as db:
                repo = ApplicationRepository(db)
                app = await repo.mark_correction_requested(app_id, reason_text)
                user_telegram_id = app.user.telegram_id if app and app.user else None
                await db.commit()
            if user_telegram_id:
                await send_to_correction(message.bot, user_telegram_id, reason_text)
            if app:
                await update_moderation_message(message.bot, app,
                    f"✏ Отправлено на исправление\nЗаявка: {app.number}")
            await message.bot.send_message(
                chat_id=message.chat.id,
                message_thread_id=message.message_thread_id,
                text="Запрос на исправление отправлен",
            )
        except Exception:
            logger.exception("admin_message: correction failed", extra={"app_id": app_id})
            await message.bot.send_message(
                chat_id=message.chat.id,
                message_thread_id=message.message_thread_id,
                text="❌ Произошла ошибка. Повторите попытку.",
            )
        return

    # --- НЕ ИСПРАВЛЕНИЕ → пересылаем ответ клиенту напрямую ---
    logger.info("admin_message: forwarding to client", extra={"thread_id": tid})
    await forward_admin_reply(message)


@router.callback_query(F.data.startswith("mod:correction:"))
async def correction_prompt(callback: CallbackQuery) -> None:
    app_id = int(callback.data.split(":")[-1])
    logger.info("correction_prompt: called", extra={"app_id": app_id})
    async with SessionLocal() as db:
        app = await ApplicationRepository(db).get(app_id)
        if not app:
            await _remove_inline_keyboard(callback)
            await callback.answer("Заявка не найдена", show_alert=True)
            return
        if app.status != ApplicationStatus.PENDING:
            logger.warning("correction_prompt: already processed", extra={"app_id": app_id, "status": app.status})
            await _remove_inline_keyboard(callback)
            await callback.answer("Заявка уже обработана", show_alert=True)
            return
        topic_id = app.moderation_topic_id
    if not topic_id:
        logger.error("correction_prompt: no moderation_topic_id", extra={"app_id": app_id})
        await callback.answer("Ошибка: тема модерации не найдена", show_alert=True)
        return
    if topic_id in _pending_corrections:
        await callback.answer("Комментарий для исправления уже ожидается", show_alert=True)
        return
    _pending_corrections[topic_id] = app_id
    logger.info("correction_prompt: stored", extra={"app_id": app_id, "topic_id": topic_id})
    await callback.bot.send_message(
        chat_id=callback.message.chat.id,
        message_thread_id=topic_id,
        text="Введите комментарий для исправления",
    )
    await callback.answer()
