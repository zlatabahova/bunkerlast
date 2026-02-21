from aiogram.fsm.state import State, StatesGroup

class AddInfo(StatesGroup):
    choosing_player = State()
    choosing_category = State()

class RandomChange(StatesGroup):
    choosing_player = State()
    choosing_category = State()

class Swap(StatesGroup):
    choosing_player1 = State()
    choosing_player2 = State()
    choosing_category = State()

class Shuffle(StatesGroup):
    choosing_category = State()

class Change(StatesGroup):
    choosing_player = State()
    choosing_category = State()
    input_new_value1 = State()
    input_new_value2 = State()
