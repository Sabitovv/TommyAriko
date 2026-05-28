from aiogram.fsm.state import State, StatesGroup


class AdminModeration(StatesGroup):
    correction_comment = State()
