from aiogram.fsm.state import State, StatesGroup

class Form(StatesGroup):
    login = State()
    name = State()
    search = State()
    ping = State()
    waiting_for_broadcast = State()
    waiting_for_broadcast_confirm = State()
    wanted = State()
