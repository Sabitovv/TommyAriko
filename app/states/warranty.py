from aiogram.fsm.state import State, StatesGroup


class WarrantyForm(StatesGroup):
    full_name = State()
    city = State()
    phone = State()
    product = State()
    article = State()
    screenshot = State()
    confirmation = State()
    correction_field = State()
    support = State()
