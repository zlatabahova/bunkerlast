from aiogram import Router, types
from aiogram.filters import Command
from config import ADMIN_ID

router = Router()

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Добро пожаловать в бота для игры «Бункер»!\n"
        "Команды для игроков:\n"
        "/room [код] - войти в комнату\n"
        "/me - моя карточка\n"
        "/info - раскрытая информация\n"
        "/card1 - использовать особое условие 1\n"
        "/card2 - использовать особое условие 2\n"
        "/help - список команд"
    )

@router.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "/room [код] - войти в комнату\n"
        "/me - моя карточка\n"
        "/info - раскрытая информация\n"
        "/card1, /card2 - использовать особые условия"
    )

@router.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer(
        "🔧 Админ-панель:\n"
        "/createroom - создать комнату\n"
        "/closeroom - закрыть комнату\n"
        "/players - список игроков\n"
        "/reload - обновить данные из таблицы\n"
        "/addinfo - добавить информацию в /info\n"
        "/random - случайно изменить карту\n"
        "/swap - обменять карты между игроками\n"
        "/shuffle - перемешать карты категории\n"
        "/change - изменить карту вручную\n"
        "/cancel - отменить текущий диалог"
    )
