from aiogram import Router, types
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
import asyncpg
from db import pool as db_pool_global
from utils import generate_room_code, get_random_unique_values
from config import ADMIN_ID
from handlers.states import AddInfo

router = Router()

# Кеш пула (будет заполнен при старте или через /reload)
pool_cache = {}

@router.message(Command("createroom"))
async def cmd_createroom(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    db_pool = db_pool_global
    async with db_pool.acquire() as conn:
        existing = await conn.fetchval("SELECT code FROM rooms WHERE is_active = TRUE")
        if existing:
            await message.answer(f"Уже есть активная комната {existing}. Сначала закройте её.")
            return
        code = generate_room_code()
        await conn.execute("INSERT INTO rooms (code) VALUES ($1)", code)
    await message.answer(f"✅ Комната создана! Код: {code}")

@router.message(Command("room"))
async def cmd_room(message: types.Message, command: CommandObject, state: FSMContext):
    if not command.args:
        await message.answer("Укажите код комнаты: /room XYZW")
        return
    code = command.args.upper()
    db_pool = db_pool_global
    async with db_pool.acquire() as conn:
        room = await conn.fetchrow("SELECT * FROM rooms WHERE code = $1 AND is_active = TRUE", code)
        if not room:
            await message.answer("Комната не найдена или уже закрыта.")
            return
        # Проверим, не в комнате ли уже игрок
        existing = await conn.fetchval("SELECT user_id FROM players WHERE user_id = $1 AND room_code = $2", message.from_user.id, code)
        if existing:
            await message.answer("Вы уже в этой комнате.")
            return
        # Если игрок был в другой комнате, удалим его оттуда
        await conn.execute("DELETE FROM players WHERE user_id = $1", message.from_user.id)
        # Запросим имя игрока
        await state.set_state(AddInfo.choosing_player)  # временно используем состояние для ввода имени
        await state.update_data(room_code=code)
        await message.answer("Введите ваше имя (как вас называть в игре):")

@router.message(AddInfo.choosing_player)
async def process_name(message: types.Message, state: FSMContext):
    data = await state.get_data()
    room_code = data['room_code']
    name = message.text.strip()
    db_pool = db_pool_global
    # Генерируем персонажа
    async with db_pool.acquire() as conn:
        # Получаем уже использованные в комнате значения
        used = await conn.fetch("SELECT bio, prof, health, hobby, luggage1, luggage2, fact, special1, special2 FROM players WHERE room_code = $1", room_code)
        used_bio = [r['bio'] for r in used]
        used_prof = [r['prof'] for r in used]
        used_health = [r['health'] for r in used]
        used_hobby = [r['hobby'] for r in used]
        used_luggage = [r['luggage1'] for r in used] + [r['luggage2'] for r in used]
        used_fact = [r['fact'] for r in used]
        used_special = [r['special1'] for r in used] + [r['special2'] for r in used]

        # Выбираем уникальные значения из пула (используем глобальный кеш pool_cache, который должен быть загружен)
        from handlers.admin_actions import pool_cache  # импортируем кеш из admin_actions
        try:
            bio = get_random_unique_values(pool_cache['bio'], used_bio)[0]
            prof = get_random_unique_values(pool_cache['prof'], used_prof)[0]
            health = get_random_unique_values(pool_cache['health'], used_health)[0]
            hobby = get_random_unique_values(pool_cache['hobby'], used_hobby)[0]
            fact = get_random_unique_values(pool_cache['fact'], used_fact)[0]
            luggage = get_random_unique_values(pool_cache['luggage'], used_luggage, 2)
            special = get_random_unique_values(pool_cache['special'], used_special, 2)
        except ValueError as e:
            await message.answer(f"Ошибка: {e}. Недостаточно уникальных карт в пуле.")
            await state.clear()
            return

        # Сохраняем игрока
        await conn.execute('''
            INSERT INTO players 
            (user_id, room_code, username, name, bio, prof, health, hobby, luggage1, luggage2, fact, special1, special2)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
        ''', message.from_user.id, room_code, message.from_user.username, name,
           bio, prof, health, hobby, luggage[0], luggage[1], fact, special[0], special[1])

    await message.answer(f"✅ Вы вошли в комнату {room_code} под именем {name}.\nВаша карточка: /me")
    await state.clear()

@router.message(Command("closeroom"))
async def cmd_closeroom(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    db_pool = db_pool_global
    async with db_pool.acquire() as conn:
        room = await conn.fetchrow("SELECT code FROM rooms WHERE is_active = TRUE")
        if not room:
            await message.answer("Нет активной комнаты.")
            return
        await conn.execute("UPDATE rooms SET is_active = FALSE WHERE code = $1", room['code'])
        await conn.execute("DELETE FROM players WHERE room_code = $1", room['code'])
    await message.answer("Комната закрыта, все игроки удалены.")

@router.message(Command("players"))
async def cmd_players(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    db_pool = db_pool_global
    async with db_pool.acquire() as conn:
        room = await conn.fetchrow("SELECT code FROM rooms WHERE is_active = TRUE")
        if not room:
            await message.answer("Нет активной комнаты.")
            return
        players = await conn.fetch("SELECT name, username FROM players WHERE room_code = $1", room['code'])
    if not players:
        await message.answer("В комнате пока нет игроков.")
        return
    text = "Игроки в комнате:\n" + "\n".join([f"• {p['name']} (@{p['username']})" for p in players])
    await message.answer(text)
