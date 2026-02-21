import logging
from aiogram import Router, types, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
import asyncpg
import random
from config import ADMIN_ID, SPREADSHEET_ID
from db import pool as db_pool_global
from google_sheets import load_from_sheets, update_pool
from handlers.states import RandomChange, Swap, Shuffle, Change
from utils import get_random_unique_values

pool_cache = {}  # будет заполнено при /reload или при старте

router = Router()

async def get_db_pool():
    return db_pool_global

@router.message(Command("reload"))
async def cmd_reload(message: types.Message, bot: Bot):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("🔄 Загрузка данных из Google Sheets...")
    try:
        categories = await load_from_sheets(SPREADSHEET_ID)
        db_pool = await get_db_pool()
        async with db_pool.acquire() as conn:
            await update_pool(conn, categories)
        global pool_cache
        pool_cache = categories
        await message.answer("✅ Данные успешно обновлены.")
    except Exception as e:
        logging.exception("Ошибка при загрузке Google Sheets")
        await message.answer(f"❌ Ошибка: {e}")

@router.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("❌ Нет активного диалога.")
        return
    await state.clear()
    await message.answer("✅ Диалог отменён.")

@router.message(Command("random"))
async def cmd_random(message: types.Message, state: FSMContext, bot: Bot):
    if message.from_user.id != ADMIN_ID:
        return
    db_pool = await get_db_pool()
    async with db_pool.acquire() as conn:
        room = await conn.fetchrow("SELECT code FROM rooms WHERE is_active = TRUE")
        if not room:
            await message.answer("❌ Нет активной комнаты.")
            return
    await state.set_state(RandomChange.choosing_player)
    await state.update_data(room_code=room['code'])
    await message.answer("Введите имя игрока:")

@router.message(RandomChange.choosing_player)
async def random_player(message: types.Message, state: FSMContext, bot: Bot):
    db_pool = await get_db_pool()
    data = await state.get_data()
    name = message.text.strip()
    async with db_pool.acquire() as conn:
        player = await conn.fetchrow(
            "SELECT user_id, name FROM players WHERE room_code = $1 AND name = $2",
            data['room_code'], name
        )
        if not player:
            await message.answer("❌ Игрок с таким именем не найден. Попробуйте ещё раз или /cancel.")
            return
    await state.update_data(player_name=name, player_id=player['user_id'])
    await state.set_state(RandomChange.choosing_category)
    await message.answer("Какую категорию изменить?\n(Биология, Профессия, Здоровье, Хобби, Багаж, Факт)")

@router.message(RandomChange.choosing_category)
async def random_category(message: types.Message, state: FSMContext, bot: Bot):
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
        await message.answer("❌ Некорректная категория. Выберите из списка.")
        return
    db_cat = cat_map[cat]
    data = await state.get_data()
    room_code = data['room_code']
    player_name = data['player_name']
    player_id = data['player_id']

    db_pool = await get_db_pool()
    async with db_pool.acquire() as conn:
        player = await conn.fetchrow("SELECT * FROM players WHERE user_id = $1", player_id)
        if not player:
            await message.answer("❌ Ошибка: игрок не найден.")
            await state.clear()
            return

        if db_cat == 'luggage':
            rows = await conn.fetch(
                "SELECT luggage1, luggage2 FROM players WHERE room_code = $1 AND user_id != $2",
                room_code, player_id
            )
            used_vals = []
            for r in rows:
                if r['luggage1']:
                    used_vals.append(r['luggage1'])
                if r['luggage2']:
                    used_vals.append(r['luggage2'])
            try:
                new_vals = get_random_unique_values(pool_cache['luggage'], used_vals, 2)
            except ValueError as e:
                await message.answer(f"❌ Недостаточно уникальных значений в пуле: {e}")
                await state.clear()
                return

            old_l1 = player['luggage1']
            old_l2 = player['luggage2']
            await conn.execute(
                "UPDATE players SET luggage1 = $1, luggage2 = $2 WHERE user_id = $3",
                new_vals[0], new_vals[1], player_id
            )
            await bot.send_message(
                player_id,
                f"🔄 Ваш багаж изменён администратором (случайно):\n"
                f"Было: {old_l1}, {old_l2}\n"
                f"Стало: {new_vals[0]}, {new_vals[1]}"
            )
            await message.answer(
                f"✅ Багаж игрока {player_name} случайно изменён:\n"
                f"Новые значения: {new_vals[0]}, {new_vals[1]}"
            )
        else:
            rows = await conn.fetch(
                f"SELECT {db_cat} FROM players WHERE room_code = $1 AND user_id != $2 AND {db_cat} IS NOT NULL",
                room_code, player_id
            )
            used_vals = [r[db_cat] for r in rows]
            try:
                new_val = get_random_unique_values(pool_cache[db_cat], used_vals, 1)[0]
            except ValueError as e:
                await message.answer(f"❌ Недостаточно уникальных значений в пуле: {e}")
                await state.clear()
                return

            old_val = player[db_cat]
            await conn.execute(
                f"UPDATE players SET {db_cat} = $1 WHERE user_id = $2",
                new_val, player_id
            )
            await bot.send_message(
                player_id,
                f"🔄 Ваша категория «{cat}» изменена администратором (случайно):\n"
                f"Было: {old_val}\n"
                f"Стало: {new_val}"
            )
            await message.answer(f"✅ {cat} игрока {player_name} изменён на «{new_val}».")
    await state.clear()

@router.message(Command("swap"))
async def cmd_swap(message: types.Message, state: FSMContext, bot: Bot):
    if message.from_user.id != ADMIN_ID:
        return
    db_pool = await get_db_pool()
    async with db_pool.acquire() as conn:
        room = await conn.fetchrow("SELECT code FROM rooms WHERE is_active = TRUE")
        if not room:
            await message.answer("❌ Нет активной комнаты.")
            return
    await state.set_state(Swap.choosing_player1)
    await state.update_data(room_code=room['code'])
    await message.answer("Введите имя первого игрока:")

@router.message(Swap.choosing_player1)
async def swap_player1(message: types.Message, state: FSMContext, bot: Bot):
    db_pool = await get_db_pool()
    data = await state.get_data()
    name1 = message.text.strip()
    async with db_pool.acquire() as conn:
        player1 = await conn.fetchrow(
            "SELECT user_id, name FROM players WHERE room_code = $1 AND name = $2",
            data['room_code'], name1
        )
        if not player1:
            await message.answer("❌ Игрок не найден. Попробуйте ещё раз.")
            return
    await state.update_data(player1_name=name1, player1_id=player1['user_id'])
    await state.set_state(Swap.choosing_player2)
    await message.answer("Введите имя второго игрока:")

@router.message(Swap.choosing_player2)
async def swap_player2(message: types.Message, state: FSMContext, bot: Bot):
    db_pool = await get_db_pool()
    data = await state.get_data()
    name2 = message.text.strip()
    if name2 == data['player1_name']:
        await message.answer("❌ Игроки должны быть разными. Введите другое имя:")
        return
    async with db_pool.acquire() as conn:
        player2 = await conn.fetchrow(
            "SELECT user_id, name FROM players WHERE room_code = $1 AND name = $2",
            data['room_code'], name2
        )
        if not player2:
            await message.answer("❌ Игрок не найден. Попробуйте ещё раз.")
            return
    await state.update_data(player2_name=name2, player2_id=player2['user_id'])
    await state.set_state(Swap.choosing_category)
    await message.answer("Какую категорию обменять?\n(Биология, Профессия, Здоровье, Хобби, Багаж, Факт)")

@router.message(Swap.choosing_category)
async def swap_category(message: types.Message, state: FSMContext, bot: Bot):
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
        await message.answer("❌ Некорректная категория. Выберите из списка.")
        return
    db_cat = cat_map[cat]
    data = await state.get_data()
    room_code = data['room_code']
    p1_id = data['player1_id']
    p2_id = data['player2_id']
    p1_name = data['player1_name']
    p2_name = data['player2_name']

    db_pool = await get_db_pool()
    async with db_pool.acquire() as conn:
        p1 = await conn.fetchrow("SELECT * FROM players WHERE user_id = $1", p1_id)
        p2 = await conn.fetchrow("SELECT * FROM players WHERE user_id = $2", p2_id)
        if not p1 or not p2:
            await message.answer("❌ Ошибка получения данных игроков.")
            await state.clear()
            return

        if db_cat == 'luggage':
            old_p1_l1, old_p1_l2 = p1['luggage1'], p1['luggage2']
            old_p2_l1, old_p2_l2 = p2['luggage1'], p2['luggage2']
            await conn.execute(
                "UPDATE players SET luggage1 = $1, luggage2 = $2 WHERE user_id = $3",
                old_p2_l1, old_p2_l2, p1_id
            )
            await conn.execute(
                "UPDATE players SET luggage1 = $1, luggage2 = $2 WHERE user_id = $3",
                old_p1_l1, old_p1_l2, p2_id
            )
            await bot.send_message(
                p1_id,
                f"🔄 Ваш багаж обменян администратором с игроком {p2_name}:\n"
                f"Теперь у вас: {old_p2_l1}, {old_p2_l2}"
            )
            await bot.send_message(
                p2_id,
                f"🔄 Ваш багаж обменян администратором с игроком {p1_name}:\n"
                f"Теперь у вас: {old_p1_l1}, {old_p1_l2}"
            )
            await message.answer(
                f"✅ Багаж игроков {p1_name} и {p2_name} обменян."
            )
        else:
            old_p1_val = p1[db_cat]
            old_p2_val = p2[db_cat]
            await conn.execute(
                f"UPDATE players SET {db_cat} = $1 WHERE user_id = $2",
                old_p2_val, p1_id
            )
            await conn.execute(
                f"UPDATE players SET {db_cat} = $1 WHERE user_id = $2",
                old_p1_val, p2_id
            )
            await bot.send_message(
                p1_id,
                f"🔄 Ваша категория «{cat}» обменяна администратором с игроком {p2_name}:\n"
                f"Теперь у вас: {old_p2_val}"
            )
            await bot.send_message(
                p2_id,
                f"🔄 Ваша категория «{cat}» обменяна администратором с игроком {p1_name}:\n"
                f"Теперь у вас: {old_p1_val}"
            )
            await message.answer(
                f"✅ {cat} игроков {p1_name} и {p2_name} обменяна."
            )
    await state.clear()

@router.message(Command("shuffle"))
async def cmd_shuffle(message: types.Message, state: FSMContext, bot: Bot):
    if message.from_user.id != ADMIN_ID:
        return
    db_pool = await get_db_pool()
    async with db_pool.acquire() as conn:
        room = await conn.fetchrow("SELECT code FROM rooms WHERE is_active = TRUE")
        if not room:
            await message.answer("❌ Нет активной комнаты.")
            return
    await state.set_state(Shuffle.choosing_category)
    await state.update_data(room_code=room['code'])
    await message.answer("Какую категорию перемешать?\n(Биология, Профессия, Здоровье, Хобби, Багаж, Факт)")

@router.message(Shuffle.choosing_category)
async def shuffle_category(message: types.Message, state: FSMContext, bot: Bot):
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
        await message.answer("❌ Некорректная категория. Выберите из списка.")
        return
    db_cat = cat_map[cat]
    data = await state.get_data()
    room_code = data['room_code']

    db_pool = await get_db_pool()
    async with db_pool.acquire() as conn:
        if db_cat == 'luggage':
            players = await conn.fetch(
                "SELECT user_id FROM players WHERE room_code = $1",
                room_code
            )
            if len(players) < 2:
                await message.answer("❌ Недостаточно игроков для перемешивания.")
                await state.clear()
                return

            # Собираем все багажи
            all_luggage = []
            for p in players:
                p_data = await conn.fetchrow("SELECT luggage1, luggage2 FROM players WHERE user_id = $1", p['user_id'])
                all_luggage.append(p_data['luggage1'])
                all_luggage.append(p_data['luggage2'])
            random.shuffle(all_luggage)
            # Раздаём по два
            for i, p in enumerate(players):
                new_l1 = all_luggage[2*i]
                new_l2 = all_luggage[2*i+1]
                await conn.execute(
                    "UPDATE players SET luggage1 = $1, luggage2 = $2 WHERE user_id = $3",
                    new_l1, new_l2, p['user_id']
                )
                await bot.send_message(
                    p['user_id'],
                    f"🔄 Багаж перемешан администратором! Ваш новый багаж:\n{new_l1}, {new_l2}"
                )
            await message.answer("✅ Багаж всех игроков перемешан.")
        else:
            rows = await conn.fetch(f"SELECT user_id, {db_cat} FROM players WHERE room_code = $1", room_code)
            if len(rows) < 2:
                await message.answer("❌ Недостаточно игроков для перемешивания.")
                await state.clear()
                return
            all_vals = [r[db_cat] for r in rows if r[db_cat] is not None]
            random.shuffle(all_vals)
            for i, row in enumerate(rows):
                new_val = all_vals[i]
                await conn.execute(f"UPDATE players SET {db_cat} = $1 WHERE user_id = $2", new_val, row['user_id'])
                await bot.send_message(
                    row['user_id'],
                    f"🔄 Категория «{cat}» перемешана администратором! Новое значение:\n{new_val}"
                )
            await message.answer(f"✅ {cat} всех игроков перемешана.")
    await state.clear()

@router.message(Command("change"))
async def cmd_change(message: types.Message, state: FSMContext, bot: Bot):
    if message.from_user.id != ADMIN_ID:
        return
    db_pool = await get_db_pool()
    async with db_pool.acquire() as conn:
        room = await conn.fetchrow("SELECT code FROM rooms WHERE is_active = TRUE")
        if not room:
            await message.answer("❌ Нет активной комнаты.")
            return
    await state.set_state(Change.choosing_player)
    await state.update_data(room_code=room['code'])
    await message.answer("Введите имя игрока:")

@router.message(Change.choosing_player)
async def change_player(message: types.Message, state: FSMContext, bot: Bot):
    db_pool = await get_db_pool()
    data = await state.get_data()
    name = message.text.strip()
    async with db_pool.acquire() as conn:
        player = await conn.fetchrow(
            "SELECT user_id, name FROM players WHERE room_code = $1 AND name = $2",
            data['room_code'], name
        )
        if not player:
            await message.answer("❌ Игрок не найден. Попробуйте ещё раз.")
            return
    await state.update_data(player_name=name, player_id=player['user_id'])
    await state.set_state(Change.choosing_category)
    await message.answer("Какую категорию изменить?\n(Биология, Профессия, Здоровье, Хобби, Багаж, Факт)")

@router.message(Change.choosing_category)
async def change_category(message: types.Message, state: FSMContext, bot: Bot):
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
        await message.answer("❌ Некорректная категория. Выберите из списка.")
        return
    db_cat = cat_map[cat]
    await state.update_data(db_cat=db_cat, cat_ru=cat)

    if db_cat == 'luggage':
        await state.set_state(Change.input_new_value1)
        await message.answer("Введите новое значение для **первого** предмета багажа:")
    else:
        await state.set_state(Change.input_new_value1)
        await message.answer(f"Введите новое значение для категории «{cat}»:")

@router.message(Change.input_new_value1)
async def change_new_value1(message: types.Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    db_cat = data['db_cat']
    new_val1 = message.text.strip()
    if not new_val1:
        await message.answer("❌ Значение не может быть пустым. Введите снова:")
        return

    if db_cat == 'luggage':
        await state.update_data(new_luggage1=new_val1)
        await state.set_state(Change.input_new_value2)
        await message.answer("Введите новое значение для **второго** предмета багажа:")
    else:
        await apply_change(message, state, bot, new_val1)

async def apply_change(message: types.Message, state: FSMContext, bot: Bot, new_val1: str, new_val2: str = None):
    data = await state.get_data()
    player_id = data['player_id']
    player_name = data['player_name']
    db_cat = data['db_cat']
    cat_ru = data['cat_ru']
    db_pool = await get_db_pool()

    async with db_pool.acquire() as conn:
        if db_cat == 'luggage':
            if new_val2 is None:
                data2 = await state.get_data()
                new_val2 = data2.get('new_luggage2')
                if not new_val2:
                    await message.answer("❌ Ошибка: второе значение багажа не найдено.")
                    await state.clear()
                    return
            old = await conn.fetchrow("SELECT luggage1, luggage2 FROM players WHERE user_id = $1", player_id)
            old_l1, old_l2 = old['luggage1'], old['luggage2']
            await conn.execute(
                "UPDATE players SET luggage1 = $1, luggage2 = $2 WHERE user_id = $3",
                new_val1, new_val2, player_id
            )
            await bot.send_message(
                player_id,
                f"🔄 Ваш багаж изменён администратором вручную:\n"
                f"Было: {old_l1}, {old_l2}\n"
                f"Стало: {new_val1}, {new_val2}"
            )
            await message.answer(
                f"✅ Багаж игрока {player_name} изменён на:\n"
                f"{new_val1}, {new_val2}"
            )
        else:
            old = await conn.fetchval(f"SELECT {db_cat} FROM players WHERE user_id = $1", player_id)
            await conn.execute(
                f"UPDATE players SET {db_cat} = $1 WHERE user_id = $2",
                new_val1, player_id
            )
            await bot.send_message(
                player_id,
                f"🔄 Ваша категория «{cat_ru}» изменена администратором вручную:\n"
                f"Было: {old}\n"
                f"Стало: {new_val1}"
            )
            await message.answer(f"✅ {cat_ru} игрока {player_name} изменён на «{new_val1}».")
    await state.clear()

@router.message(Change.input_new_value2)
async def change_new_value2(message: types.Message, state: FSMContext, bot: Bot):
    new_val2 = message.text.strip()
    if not new_val2:
        await message.answer("❌ Значение не может быть пустым. Введите снова:")
        return
    data = await state.get_data()
    new_val1 = data.get('new_luggage1')
    if not new_val1:
        await message.answer("❌ Ошибка: первое значение багажа не найдено. Начните заново.")
        await state.clear()
        return
    await apply_change(message, state, bot, new_val1, new_val2)
