from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="▶ Начать активацию", callback_data="start_activation")],
            [InlineKeyboardButton(text="💬 Задать вопрос", callback_data="ask_question")],
        ]
    )


def phone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить контакт", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_application")],
            [InlineKeyboardButton(text="✏ Изменить данные", callback_data="edit_application")],
        ]
    )


def edit_fields_keyboard(prefix: str = "edit_field") -> InlineKeyboardMarkup:
    fields = ["ФИО", "Город", "Телефон", "Категория", "Артикул", "Скриншот"]
    builder = InlineKeyboardBuilder()
    for field in fields:
        builder.button(text=field, callback_data=f"{prefix}:{field}")
    builder.adjust(2)
    return builder.as_markup()


def products_reply_keyboard(products: list[dict]) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=p["name"])] for p in products]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def support_chat_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="◀️ В меню")]],
        resize_keyboard=True,
    )


def moderation_keyboard(app_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"mod:approve:{app_id}")],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"mod:reject:{app_id}")],
            [InlineKeyboardButton(text="✏ Запросить исправление", callback_data=f"mod:correction:{app_id}")],
        ]
    )
