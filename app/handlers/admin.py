import logging

from aiogram import F, Router
from aiogram.filters import Filter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.config import get_settings
from app.db import SessionLocal
from app.models.entities import ApplicationStatus
from app.repositories.core import ApplicationRepository
from app.services.moderation_service import update_moderation_message, send_approved, send_rejected, send_to_correction
from app.states.admin import AdminModeration

logger = logging.getLogger(__name__)

_pending_rejects: dict[int, int] = {}  # thread_id -> app_id


class _PendingReject(Filter):
    async def __call__(self, message: Message) -> bool:
        tid = message.message_thread_id
        if tid is None:
            return False
        result = tid in _pending_rejects
        logger.info(
            "_PendingReject: filter check",
            extra={
                "thread_id": tid,
                "found": result,
                "message_text": message.text[:50] if message.text else None,
                "pending_keys": list(_pending_rejects.keys()),
                "message_from": message.from_user.id if message.from_user else None,
                "chat_id": message.chat.id,
                "message_id": message.message_id,
            }
        )
        return result


router = Router()


@router.callback_query(F.data.startswith("mod:approve:"))
async def approve(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    app_id = int(callback.data.split(":")[-1])
    async with SessionLocal() as db:
        repo = ApplicationRepository(db)
        app = await repo.get(app_id)
        if app and app.status not in (ApplicationStatus.PENDING, ApplicationStatus.NEEDS_CORRECTION):
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
    logger.info("reject_prompt: callback received", extra={"app_id": app_id, "callback_chat_id": callback.message.chat.id})
    
    async with SessionLocal() as db:
        app = await ApplicationRepository(db).get(app_id)
        if not app:
            logger.error("reject_prompt: app not found", extra={"app_id": app_id})
            await callback.answer("Заявка не найдена", show_alert=True)
            return
        if app.status not in (ApplicationStatus.PENDING, ApplicationStatus.NEEDS_CORRECTION):
            logger.warning("reject_prompt: app already processed", extra={"app_id": app_id, "status": app.status})
            await callback.answer("Заявка уже обработана", show_alert=True)
            return
        topic_id = app.moderation_topic_id
        logger.info("reject_prompt: got topic_id", extra={"app_id": app_id, "topic_id": topic_id})
    
    if not topic_id:
        logger.error("reject_prompt: no moderation_topic_id", extra={"app_id": app_id})
        await callback.answer("Ошибка: тема модерации не найдена", show_alert=True)
        return
    
    _pending_rejects[topic_id] = app_id
    logger.info(
        "reject_prompt: stored app_id",
        extra={
            "topic_id": topic_id,
            "app_id": app_id,
            "all_pending": dict(_pending_rejects),
            "callback_message_thread_id": callback.message.message_thread_id,
        }
    )
    
    try:
        msg = await callback.bot.send_message(
            chat_id=callback.message.chat.id,
            message_thread_id=topic_id,
            text="Введите причину отказа",
        )
        logger.info("reject_prompt: message sent", extra={"msg_id": msg.message_id, "thread_id": topic_id})
    except Exception as e:
        logger.exception("reject_prompt: send_message failed", extra={"topic_id": topic_id, "error": str(e)})
        _pending_rejects.pop(topic_id, None)
        await callback.answer(f"Ошибка отправки: {str(e)}", show_alert=True)
        return
    
    await callback.answer()


# ГЛАВНОЕ ИЗМЕНЕНИЕ: Обработчик ПЕРЕД всеми фильтрами, чтобы поймать сообщение
@router.message(F.chat.id == get_settings().admin_group_id, F.message_thread_id.is_not(None), F.text)
async def reject_reason_or_forward(message: Message) -> None:
    """
    Обработчик для сообщений в темах админ-группы.
    Сначала проверяем, это ли отказ модерации, если нет - передаём дальше.
    """
    logger.info("reject_reason_or_forward: HANDLER_CALLED", extra={"thread_id": message.message_thread_id, "pending_keys": list(_pending_rejects.keys())})
    tid = message.message_thread_id
    
    # Проверяем, ожидаем ли мы отказ в этой теме
    if tid not in _pending_rejects:
        logger.debug(
            "reject_reason_or_forward: not a rejection reason",
            extra={
                "thread_id": tid,
                "pending_keys": list(_pending_rejects.keys()),
                "text": message.text[:50] if message.text else None,
            }
        )
        # Не наш обработчик - пусть обработает forward_admin_reply
        return
    
    # ✅ ЭТО ОТКАЗ МОДЕРАЦИИ!
    app_id = _pending_rejects.pop(tid, None)
    logger.info(
        "reject_reason: handler called",
        extra={
            "thread_id": tid,
            "app_id": app_id,
            "text_len": len(message.text),
            "from_user": message.from_user.id if message.from_user else None,
        }
    )
    
    if app_id is None:
        logger.warning("reject_reason: app_id is None", extra={"thread_id": tid})
        return
    
    try:
        async with SessionLocal() as db:
            repo = ApplicationRepository(db)
            await repo.set_status(app_id, ApplicationStatus.REJECTED, message.text)
            app = await repo.get(app_id)
            user_telegram_id = app.user.telegram_id if app and app.user else None
            await db.commit()
            logger.info("reject_reason: status updated", extra={"app_id": app_id, "user_id": user_telegram_id})
        
        if user_telegram_id:
            await send_rejected(message.bot, user_telegram_id, message.text)
            logger.info("reject_reason: rejection message sent to user", extra={"user_id": user_telegram_id})
        
        if app:
            await update_moderation_message(message.bot, app,
                f"❌ Отклонено\nЗаявка: {app.number}\nПричина: {message.text}")
            logger.info("reject_reason: moderation message updated", extra={"app_id": app_id})
        
        await message.answer("✅ Заявка отклонена")
        logger.info("reject_reason: completed successfully", extra={"app_id": app_id})
    except Exception as e:
        logger.exception("reject_reason: failed", extra={"app_id": app_id, "error": str(e)})
        await message.answer("❌ Произошла ошибка. Повторите попытку.")


@router.callback_query(F.data.startswith("mod:correction:"))
async def correction_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    app_id = int(callback.data.split(":")[-1])
    async with SessionLocal() as db:
        app = await ApplicationRepository(db).get(app_id)
        if app and app.status != ApplicationStatus.PENDING:
            await callback.answer("Заявка уже обработана", show_alert=True)
            return
    await state.update_data(correction_app_id=app_id)
    await state.set_state(AdminModeration.correction_comment)
    await callback.message.answer("Введите комментарий для исправления")
    await callback.answer()


@router.message(AdminModeration.correction_comment, F.text)
async def correction_send(message: Message, state: FSMContext) -> None:
    try:
        data = await state.get_data()
        app_id = data.get("correction_app_id")
        if not app_id:
            await state.clear()
            await message.answer("Ошибка: заявка не найдена. Начните заново.")
            return
        async with SessionLocal() as db:
            repo = ApplicationRepository(db)
            app = await repo.mark_correction_requested(app_id, message.text)
            user_telegram_id = app.user.telegram_id if app and app.user else None
            await db.commit()
        if user_telegram_id:
            await send_to_correction(message.bot, user_telegram_id, message.text)
        if app:
            await update_moderation_message(message.bot, app, f"✏ Отправлено на исправление\nЗаявка: {app.number}")
        await state.clear()
        await message.answer("Запрос на исправление отправлен")
    except Exception:
        logger.exception("correction_send_failed")
        await state.clear()
        await message.answer("Произошла ошибка. Повторите попытку.")
