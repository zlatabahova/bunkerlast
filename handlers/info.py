from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
import asyncpg
from db import get_pool
from config import ADMIN_ID
from handlers.states import AddInfo

router = Router()

@router.message(Command("info"))
async def cmd_info(message: types.Message):
    pool = get_pool()
    async with pool.acquire() as conn:
        # Найдём комнату игрока (если игрок)
        player = await conn.fetchrow("SELECT room_code FROM players WHERE user_id = $1", message.from_user.id)
        if player:
            room_code = player['room_code']
        else:
            # Если админ вне комнаты
            if message.from_user.id == ADMIN_ID:
                room = await conn.fetchrow("SELECT code FROM rooms WHERE is_active = TRUE")
                if not room:
                    await message.answer("Нет активной комнаты.")
                    return
                room_code = room['code']
            else:
                await message.answer("Вы не в комнате.")
                return

        # Получаем всех игроков комнаты
        players = await conn.fetch("SELECT name, bio, prof, health, hobby, luggage1, luggage2, fact, revealed FROM players WHERE room_code = $1", room_code)
        if not players:
            await message.answer("В комнате нет игроков.")
            return

        text = "📢 Раскрытая информация:\n"
        for p in players:
            revealed = p['revealed'] or []
            if not revealed:
                continue
            player_text = f"\n{p['name']}\n"
            for cat in revealed:
                if cat == 'bio':
                    player_text += f"🧬 Биология: {p['bio']}\n"
                elif cat == 'prof':
                    player_text += f"💼 Профессия: {p['prof']}\n"
                elif cat == 'health':
                    player_text += f"❤️ Здоровье: {p['health']}\n"
                elif cat == 'hobby':
                    player_text += f"🎨 Хобби: {p['hobby']}\n"
                elif cat == 'luggage':
                    player_text += f"🎒 Багаж: {p['luggage1']}, {p['luggage2']}\n"
                elif cat == 'fact':
                    player_text += f"📜 Факт: {p['fact']}\n"
                # Особое условие не раскрывается
            text += player_text
        await message.answer(text if text != "📢 Раскрытая информация:\n" else "Пока ничего не раскрыто.")

@router.message(Command("addinfo"))
async def cmd_addinfo(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    pool = get_pool()
    async with pool.acquire() as conn:
        room = await conn.fetchrow("SELECT code FROM rooms WHERE is_active = TRUE")
        if not room:
            await message.answer("Нет активной комнаты.")
            return
    await state.set_state(AddInfo.choosing_player)
    await state.update_data(room_code=room['code'])
    await message.answer("Введите имя игрока, которому хотите раскрыть информацию:")

@router.message(AddInfo.choosing_player)
async def addinfo_player(message: types.Message, state: FSMContext):
    data = await state.get_data()
    room_code = data['room_code']
    name = message.text.strip()
    pool = get_pool()
    async with pool.acquire() as conn:
        player = await conn.fetchrow("SELECT name FROM players WHERE room_code = $1 AND name = $2", room_code, name)
        if not player:
            await message.answer("Игрок с таким именем не найден. Попробуйте ещё раз.")
            return
    await state.update_data(player_name=name)
    await state.set_state(AddInfo.choosing_category)
    await message.answer("Какую категорию раскрыть? (Биология, Профессия, Здоровье, Хобби, Багаж, Факт)")

@router.message(AddInfo.choosing_category)
async def addinfo_category(message: types.Message, state: FSMContext):
    cat_map = {
        "биология": "bio",
        "профессия": "prof",
        "здоровье": "health",
        "хобби": "hobby",
        "багаж": "luggage",
        "факт": "fact"
    }
    cat = message.text.strip().lower()
    if cat not in cat_map:
        await message.answer("Некорректная категория. Выберите из списка.")
        return
    db_cat = cat_map[cat]
    data = await state.get_data()
    pool = get_pool()
    async with pool.acquire() as conn:
        # Добавляем категорию в массив revealed игрока (избегаем дублей)
        await conn.execute("UPDATE players SET revealed = array_append(revealed, $1) WHERE room_code = $2 AND name = $3 AND NOT ($1 = ANY(revealed))", db_cat, data['room_code'], data['player_name'])
    await message.answer(f"Категория {cat} раскрыта для игрока {data['player_name']}.")
    await state.clear()
