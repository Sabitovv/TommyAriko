from pathlib import Path
import logging

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ContentType, Message, ReplyKeyboardRemove

from app.db import SessionLocal
from app.keyboards.common import (
    confirmation_keyboard,
    edit_fields_keyboard,
    phone_keyboard,
    products_reply_keyboard,
    support_chat_keyboard,
    start_keyboard,
)
from app.repositories.core import ApplicationRepository, ProductRepository, SessionRepository, SupportRepository, UserRepository
from app.services.moderation_service import publish_application_for_moderation
from app.states.warranty import WarrantyForm
from app.utils.validators import validate_article, validate_full_name, validate_phone

router = Router()
logger = logging.getLogger(__name__)

WELCOME = (
    "👋 Добро пожаловать!\n\n"
    "Выберите действие на клавиатуре ниже:\n"
    "• `▶ Начать активацию` — оформить гарантию\n"
    "• `💬 Задать вопрос` — написать в поддержку\n\n"
    "При активации гарантии важно отвечать точно: неверные данные могут привести к отклонению заявки.\n"
    "⏳ Таймаут на каждом шаге: 30 минут, после чего сессия завершается автоматически."
)


async def _send_confirmation_summary(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    text = (
        "✅ 🔶 Шаг 7/7. Проверьте данные\n"
        "Внимательно проверьте всю указанную информацию, включая данные о товаре и отзыв на Wildberries.\n"
        "Если информация будет указана неверно или не полностью, гарантийный талон не будет принят.\n\n"
        f"1) ФИО: {data['full_name']}\n"
        f"2) Город: {data['city']}\n"
        f"3) Телефон: {data['phone']}\n"
        f"4) Товар: {data['category']}\n"
        f"5) Артикул: {data['article']}"
    )
    await message.answer(text, reply_markup=confirmation_keyboard())


async def _touch_session_state(telegram_id: int, username: str | None, state_name: str) -> None:
    async with SessionLocal() as db:
        user = await UserRepository(db).get_or_create(telegram_id, username)
        await SessionRepository(db).touch(user.id, state_name)
        await db.commit()


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(WELCOME, reply_markup=start_keyboard())


@router.callback_query(F.data == "start_activation")
async def begin(callback: CallbackQuery, state: FSMContext) -> None:
    logger.info("start_activation_clicked", extra={"user_id": callback.from_user.id})
    await state.clear()
    await state.set_state(WarrantyForm.full_name)
    await _touch_session_state(callback.from_user.id, callback.from_user.username, "FORM_FULL_NAME")
    if callback.message:
        await callback.message.answer("🔶 Шаг 1/7. Введите ФИО\nУкажите фамилию, имя и отчество полностью.")
    await callback.answer("Начинаем активацию")


@router.message(F.text.contains("Начать активацию"))
async def begin_from_text(message: Message, state: FSMContext) -> None:
    logger.info("start_activation_text", extra={"user_id": message.from_user.id})
    await state.clear()
    await state.set_state(WarrantyForm.full_name)
    await _touch_session_state(message.from_user.id, message.from_user.username, "FORM_FULL_NAME")
    await message.answer("🔶 Шаг 1/7. Введите ФИО\nУкажите фамилию, имя и отчество полностью.")


@router.message(WarrantyForm.full_name)
async def step_full_name(message: Message, state: FSMContext) -> None:
    if not message.text or not validate_full_name(message.text):
        await message.answer("Введите корректное ФИО (минимум 2 слова)")
        return
    await state.update_data(full_name=message.text)
    await state.set_state(WarrantyForm.city)
    await _touch_session_state(message.from_user.id, message.from_user.username, "FORM_CITY")
    await message.answer("🔶 Шаг 2/7. Введите город\nПример: Москва")


@router.message(WarrantyForm.city)
async def step_city(message: Message, state: FSMContext) -> None:
    await state.update_data(city=message.text)
    await state.set_state(WarrantyForm.phone)
    await _touch_session_state(message.from_user.id, message.from_user.username, "FORM_PHONE")
    await message.answer(
        "📞 🔶 Шаг 3/7. Введите номер телефона\n"
        "Нажмите кнопку ниже, чтобы отправить номер из Telegram,\n"
        "или введите номер вручную в формате +79991234567.",
        reply_markup=phone_keyboard(),
    )


@router.message(WarrantyForm.phone, F.contact)
async def step_phone_contact(message: Message, state: FSMContext) -> None:
    phone = message.contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone
    await _to_product_step(message, state, phone)


@router.message(WarrantyForm.phone)
async def step_phone_text(message: Message, state: FSMContext) -> None:
    if not message.text or not validate_phone(message.text):
        await message.answer("Неверный формат. Пример: +79991234567")
        return
    await _to_product_step(message, state, message.text)


async def _to_product_step(message: Message, state: FSMContext, phone: str) -> None:
    await state.update_data(phone=phone)
    async with SessionLocal() as db:
        rows = await ProductRepository(db).get_deduped_products()
        categories: dict[str, dict] = {}
        for p in rows:
            categories.setdefault(p.category, {"id": p.id, "name": p.category})
        products = list(categories.values())
    if not products:
        await message.answer(
            "Список товаров пока пуст. Мы синхронизируем товары из WB API. "
            "Попробуйте через несколько минут или обратитесь в поддержку."
        )
        return
    await state.update_data(products=products)
    await state.set_state(WarrantyForm.product)
    await _touch_session_state(message.from_user.id, message.from_user.username, "FORM_PRODUCT")
    await message.answer(
        "📦 🔶 Шаг 4/7. Выберите категорию\nВыберите категорию приобретенного товара:",
        reply_markup=products_reply_keyboard(products),
    )


@router.message(WarrantyForm.product)
async def product_by_text(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Выберите товар кнопкой с клавиатуры ниже.")
        return

    data = await state.get_data()
    products = data.get("products", [])

    picked = next((p for p in products if p["name"] == message.text), None)
    if not picked:
        await message.answer("Пожалуйста, выберите товар кнопкой с клавиатуры.")
        return

    pid = picked["id"]
    async with SessionLocal() as db:
        product = await ProductRepository(db).get_by_id(pid)
    if not product:
        await message.answer("Товар не найден. Выберите другой из списка.")
        return
    await state.update_data(category=product.category)
    await state.set_state(WarrantyForm.article)
    await _touch_session_state(message.from_user.id, message.from_user.username, "FORM_ARTICLE")
    await message.answer(
        "🏷️ 🔶 Шаг 5/7. Введите артикул\n"
        "Артикул указан на внешней стороне упаковки.\n"
        "Формат: только цифры.",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(WarrantyForm.article)
async def step_article(message: Message, state: FSMContext) -> None:
    if not message.text or not validate_article(message.text):
        await message.answer("Артикул должен содержать только цифры.")
        return
    data = await state.get_data()
    async with SessionLocal() as db:
        row = await ProductRepository(db).valid_article_by_category(data["category"], message.text)
    if not row:
        await message.answer(
            "❌ Артикул не найден в каталоге выбранной категории. "
            "Проверьте категорию и введите правильный артикул."
        )
        return
    await state.update_data(product_id=row.id, product_name=row.name)
    await state.update_data(article=message.text)
    await state.set_state(WarrantyForm.screenshot)
    await _touch_session_state(message.from_user.id, message.from_user.username, "FORM_SCREENSHOT")
    await message.answer(
        "🖼️ 🔶 Шаг 6/7. Загрузите скриншот отзыва\n"
        "Оставьте отзыв о товаре на Wildberries и отправьте скриншот.\n"
        "Принимается только изображение."
    )


@router.message(WarrantyForm.screenshot, F.content_type == ContentType.PHOTO)
async def step_screenshot(message: Message, state: FSMContext) -> None:
    photo = message.photo[-1]
    media_dir = Path("storage/media")
    media_dir.mkdir(parents=True, exist_ok=True)
    path = media_dir / f"{message.from_user.id}_{photo.file_unique_id}.jpg"
    await message.bot.download(photo, destination=path)
    await state.update_data(screenshot_file_id=photo.file_id, screenshot_path=str(path))
    await state.set_state(WarrantyForm.confirmation)
    await _touch_session_state(message.from_user.id, message.from_user.username, "FORM_CONFIRMATION")
    await _send_confirmation_summary(message, state)


@router.message(WarrantyForm.screenshot)
async def step_screenshot_invalid(message: Message) -> None:
    await message.answer("Нужен именно скриншот-изображение.")


@router.callback_query(F.data == "edit_application")
async def edit_app(callback: CallbackQuery, state: FSMContext) -> None:
    async with SessionLocal() as db:
        user = await UserRepository(db).get_or_create(callback.from_user.id, callback.from_user.username)
        app = await ApplicationRepository(db).latest_needs_correction_by_user(user.id)

    if app:
        await state.set_state(WarrantyForm.confirmation)
        await state.update_data(
            editing_application_id=app.id,
            full_name=app.customer_full_name,
            city=app.city,
            phone=app.phone,
            product_id=app.product_id,
            product_name=app.product.name,
            category=app.product.category,
            article=app.article,
            screenshot_file_id=app.screenshot_file_id,
            screenshot_path=app.screenshot_path,
        )
    await callback.message.answer("Выберите поле для исправления:", reply_markup=edit_fields_keyboard())
    await callback.answer()


@router.callback_query(WarrantyForm.confirmation, F.data.startswith("edit_field:"))
async def edit_field(callback: CallbackQuery, state: FSMContext) -> None:
    field = callback.data.split(":", 1)[1]
    await state.update_data(editing_field=field)
    await state.set_state(WarrantyForm.correction_field)

    if field == "Категория":
        async with SessionLocal() as db:
            rows = await ProductRepository(db).get_deduped_products()
            categories: dict[str, dict] = {}
            for p in rows:
                categories.setdefault(p.category, {"id": p.id, "name": p.category})
            products = list(categories.values())
        await state.update_data(products=products)
        await callback.message.answer(
            "Выберите новую категорию:",
            reply_markup=products_reply_keyboard(products),
        )
    elif field == "Телефон":
        await callback.message.answer(
            "Введите новый номер телефона в формате +79991234567 "
            "или отправьте контакт кнопкой ниже.",
            reply_markup=phone_keyboard(),
        )
    elif field == "Скриншот":
        await callback.message.answer("Отправьте новый скриншот отзыва (только изображение).")
    else:
        await callback.message.answer(f"Введите новое значение: {field}")
    await callback.answer()


@router.message(WarrantyForm.correction_field, F.contact)
async def correction_contact(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("editing_field") != "Телефон":
        await message.answer("Сейчас редактируется другое поле. Используйте кнопки изменения данных.")
        return
    phone = message.contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone
    if not validate_phone(phone):
        await message.answer("Неверный формат. Пример: +79991234567")
        return
    await state.update_data(phone=phone)
    await state.update_data(editing_field=None)
    await state.set_state(WarrantyForm.confirmation)
    await _send_confirmation_summary(message, state)


@router.message(WarrantyForm.correction_field, F.content_type == ContentType.PHOTO)
async def correction_photo(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("editing_field") != "Скриншот":
        await message.answer("Сейчас редактируется другое поле. Используйте кнопки изменения данных.")
        return
    photo = message.photo[-1]
    media_dir = Path("storage/media")
    media_dir.mkdir(parents=True, exist_ok=True)
    path = media_dir / f"{message.from_user.id}_{photo.file_unique_id}.jpg"
    await message.bot.download(photo, destination=path)
    await state.update_data(screenshot_file_id=photo.file_id, screenshot_path=str(path), editing_field=None)
    await state.set_state(WarrantyForm.confirmation)
    await _send_confirmation_summary(message, state)


@router.message(WarrantyForm.correction_field)
async def correction_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    field = data.get("editing_field")
    text = (message.text or "").strip()

    if field == "ФИО":
        if not validate_full_name(text):
            await message.answer("Введите корректное ФИО (минимум 2 слова)")
            return
        await state.update_data(full_name=text, editing_field=None)
        await state.set_state(WarrantyForm.confirmation)
        await _send_confirmation_summary(message, state)
        return

    if field == "Город":
        if not text:
            await message.answer("Введите город")
            return
        await state.update_data(city=text, editing_field=None)
        await state.set_state(WarrantyForm.confirmation)
        await _send_confirmation_summary(message, state)
        return

    if field == "Телефон":
        if not validate_phone(text):
            await message.answer("Неверный формат. Пример: +79991234567")
            return
        await state.update_data(phone=text, editing_field=None)
        await state.set_state(WarrantyForm.confirmation)
        await _send_confirmation_summary(message, state)
        return

    if field == "Категория":
        products = data.get("products", [])

        picked = next((p for p in products if p["name"] == text), None)
        if not picked:
            await message.answer("Пожалуйста, выберите категорию кнопкой с клавиатуры.")
            return

        await state.update_data(category=picked["name"], editing_field=None)
        await state.set_state(WarrantyForm.confirmation)
        await _send_confirmation_summary(message, state)
        return

    if field == "Артикул":
        if not validate_article(text):
            await message.answer("Артикул должен содержать только цифры.")
            return
        category = data.get("category")
        async with SessionLocal() as db:
            row = await ProductRepository(db).valid_article_by_category(category, text)
        if not row:
            await message.answer(
                "❌ Артикул не найден в каталоге выбранной категории. "
                "Проверьте категорию и введите правильный артикул."
            )
            return
        await state.update_data(article=text, product_id=row.id, product_name=row.name, editing_field=None)
        await state.set_state(WarrantyForm.confirmation)
        await _send_confirmation_summary(message, state)
        return

    if field == "Скриншот":
        await message.answer("Принимается только изображение. Отправьте фото-скриншот.")
        return

    await message.answer("Не удалось определить поле для редактирования. Нажмите /start и начните заново.")


@router.callback_query(WarrantyForm.confirmation, F.data == "confirm_application")
async def confirm(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    async with SessionLocal() as db:
        user_repo = UserRepository(db)
        app_repo = ApplicationRepository(db)
        support_repo = SupportRepository(db)
        session_repo = SessionRepository(db)
        user = await user_repo.get_or_create(callback.from_user.id, callback.from_user.username)
        support_topic = await support_repo.get_by_user(user.id)
        canonical_topic_id = support_topic.topic_id if support_topic else await app_repo.get_user_moderation_topic_id(user.id)
        edit_id = data.get("editing_application_id")
        if edit_id:
            app = await app_repo.get(edit_id)
            if not app:
                await callback.message.answer("Заявка для исправления не найдена. Начните заново: /start")
                await state.clear()
                await callback.answer()
                return
            app = await app_repo.update_from_user_form(
                app,
                full_name=data["full_name"],
                city=data["city"],
                phone=data["phone"],
                product_id=data["product_id"],
                article=data["article"],
                screenshot_file_id=data["screenshot_file_id"],
                screenshot_path=data["screenshot_path"],
            )
            if canonical_topic_id:
                app.moderation_topic_id = canonical_topic_id
        else:
            number = await app_repo.next_number()
            app = await app_repo.create(
                number=number,
                user_id=user.id,
                product_id=data["product_id"],
                customer_full_name=data["full_name"],
                city=data["city"],
                phone=data["phone"],
                article=data["article"],
                screenshot_file_id=data["screenshot_file_id"],
                screenshot_path=data["screenshot_path"],
            )
            if canonical_topic_id:
                app.moderation_topic_id = canonical_topic_id
        await session_repo.touch(user.id, "PENDING_MODERATION")
        app.user = user
        app.product = await ProductRepository(db).get_by_id(data["product_id"])
        await publish_application_for_moderation(callback.bot, app)
        if app.moderation_topic_id:
            await support_repo.set_topic_for_user(user.id, app.moderation_topic_id)
        await db.commit()

    await callback.message.answer(f"Заявка {app.number} отправлена на модерацию.")
    await callback.message.answer(
        "Если хотите, можете сразу начать новую активацию или написать в поддержку.",
        reply_markup=start_keyboard(),
    )
    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "ask_question")
async def ask_question(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(WarrantyForm.support)
    await _touch_session_state(callback.from_user.id, callback.from_user.username, "SUPPORT_CHAT")
    await callback.message.answer(
        "Вы в режиме поддержки. Пишите вопросы сообщениями.\n"
        "Чтобы выйти, нажмите «◀️ В меню».",
        reply_markup=support_chat_keyboard(),
    )
    await callback.answer()


@router.message(F.text.contains("Задать вопрос"))
async def ask_question_text(message: Message, state: FSMContext) -> None:
    await state.set_state(WarrantyForm.support)
    await _touch_session_state(message.from_user.id, message.from_user.username, "SUPPORT_CHAT")
    await message.answer(
        "Вы в режиме поддержки. Пишите вопросы сообщениями.\n"
        "Чтобы выйти, нажмите «◀️ В меню».",
        reply_markup=support_chat_keyboard(),
    )


@router.message(WarrantyForm.support, F.text == "◀️ В меню")
async def support_exit_to_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _touch_session_state(message.from_user.id, message.from_user.username, "MENU")
    await message.answer(WELCOME, reply_markup=start_keyboard())


@router.message(WarrantyForm.support)
async def support_message(message: Message, state: FSMContext) -> None:
    from app.services.support_service import forward_user_question

    if not message.text:
        await message.answer("Отправьте текстовый вопрос или нажмите «◀️ В меню».")
        return
    await _touch_session_state(message.from_user.id, message.from_user.username, "SUPPORT_CHAT")
    await forward_user_question(message)
    await message.answer("Ваш вопрос передан в поддержку. Можете отправить следующий вопрос.")
