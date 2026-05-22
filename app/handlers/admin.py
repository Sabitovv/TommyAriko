from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.db import SessionLocal
from app.models.entities import ApplicationStatus
from app.repositories.core import ApplicationRepository
from app.services.moderation_service import send_approved, send_rejected, send_to_correction
from app.states.admin import AdminModeration

router = Router()


@router.callback_query(F.data.startswith("mod:approve:"))
async def approve(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    app_id = int(callback.data.split(":")[-1])
    async with SessionLocal() as db:
        repo = ApplicationRepository(db)
        await repo.set_status(app_id, ApplicationStatus.APPROVED)
        app = await repo.get(app_id)
        await db.commit()
    if app:
        await send_approved(callback.bot, app)
    await callback.answer("Одобрено")


@router.callback_query(F.data.startswith("mod:reject:"))
async def reject_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    app_id = int(callback.data.split(":")[-1])
    await state.update_data(reject_app_id=app_id)
    await state.set_state(AdminModeration.reject_reason)
    await callback.message.answer("Введите причину отказа")
    await callback.answer()


@router.message(AdminModeration.reject_reason, F.text)
async def reject_reason(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    app_id = data["reject_app_id"]
    async with SessionLocal() as db:
        repo = ApplicationRepository(db)
        await repo.set_status(app_id, ApplicationStatus.REJECTED, message.text)
        app = await repo.get(app_id)
        user_telegram_id = app.user.telegram_id if app and app.user else None
        await db.commit()
    if user_telegram_id:
        await send_rejected(message.bot, user_telegram_id, message.text)
    await state.clear()
    await message.answer("Отклонено")


@router.callback_query(F.data.startswith("mod:correction:"))
async def correction_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    app_id = int(callback.data.split(":")[-1])
    await state.update_data(correction_app_id=app_id)
    await state.set_state(AdminModeration.correction_comment)
    await callback.message.answer("Введите комментарий для исправления")
    await callback.answer()


@router.message(AdminModeration.correction_comment, F.text)
async def correction_send(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    app_id = data["correction_app_id"]
    async with SessionLocal() as db:
        repo = ApplicationRepository(db)
        app = await repo.mark_correction_requested(app_id, message.text)
        user_telegram_id = app.user.telegram_id if app and app.user else None
        await db.commit()
    if user_telegram_id:
        await send_to_correction(message.bot, user_telegram_id, message.text)
    await state.clear()
    await message.answer("Запрос на исправление отправлен")
