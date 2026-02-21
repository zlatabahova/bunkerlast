from aiogram import Router, types, Bot
from aiogram.filters import Command
import asyncpg
from db import pool as db_pool_global
from config import ADMIN_ID

router = Router()

def format_player_card(player):
    return (
        f"🧑 {player['name']}\n"
        f"🧬 Биология: {player['bio']}\n"
        f"💼 Профессия: {player['prof']}\n"
        f"❤️ Здоровье: {player['health']}\n"
        f"🎨 Хобби: {player['hobby']}\n"
        f"🎒 Багаж: {player['luggage1']}, {player['luggage2']}\n"
        f"📜 Факт: {player['fact']}\n"
        f"🔮 Особое условие: {player['special1']}, {player['special2']}"
    )

@router.message(Command("me"))
async def cmd_me(message: types.Message):
    db_pool = db_pool_global
    async with db_pool.acquire() as conn:
        player = await conn.fetchrow("SELECT * FROM players WHERE user_id = $1", message.from_user.id)
        if not player:
            await message.answer("Вы не находитесь в комнате. Войдите через /room")
            return
    await message.answer(format_player_card(player))

@router.message(Command("card1"))
@router.message(Command("card2"))
async def cmd_card(message: types.Message, bot: Bot):
    card_num = 1 if message.text == "/card1" else 2
    db_pool = db_pool_global
    async with db_pool.acquire() as conn:
        player = await conn.fetchrow("SELECT * FROM players WHERE user_id = $1", message.from_user.id)
        if not player:
            await message.answer("Вы не в комнате.")
            return
        used_field = f"used_special{card_num}"
        special_field = f"special{card_num}"
        used = player[used_field]
        special = player[special_field]

        if not special:
            await message.answer("У вас нет особого условия для этой карты.")
            # Уведомить админа
            await bot.send_message(ADMIN_ID, f"⚠️ Игрок {player['name']} попытался использовать пустую карту {card_num}.")
            return

        if used:
            await message.answer("Вы уже использовали эту карту.")
            return

        # Помечаем использованной
        await conn.execute(f"UPDATE players SET {used_field}=TRUE WHERE user_id=$1", message.from_user.id)
        # Отправляем уведомление админу
        await bot.send_message(
            ADMIN_ID,
            f"🎴 Игрок {player['name']} использовал особое условие {card_num}:\n{special}"
        )
        await message.answer(f"Вы использовали особое условие: {special}")
