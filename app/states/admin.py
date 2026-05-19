from aiogram.fsm.state import State, StatesGroup


class AdminModeration(StatesGroup):
    reject_reason = State()
    correction_comment = State()
