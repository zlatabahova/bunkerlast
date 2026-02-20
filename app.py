#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Telegram бот для игры "Бункер"
Полностью рабочий код для развертывания на Render
Исправлена проблема с event loop и сигналами в фоновом потоке.
"""

import os
import sys
import logging
import sqlite3
import random
import csv
import requests
import json
import threading
import asyncio
import traceback
from io import StringIO
from functools import wraps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    CallbackContext,
    CallbackQueryHandler,
)
from flask import Flask, jsonify

# ================== НАСТРОЙКИ ==================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    print("❌ Ошибка: не задана переменная окружения TELEGRAM_TOKEN")
    sys.exit(1)

GOOGLE_SHEETS_CSV_URL = os.environ.get("SHEETS_URL")
if not GOOGLE_SHEETS_CSV_URL:
    print("⚠️ Внимание: SHEETS_URL не задана. Бот будет работать с пустыми пулами персонажей.")
    GOOGLE_SHEETS_CSV_URL = ""

ADMIN_ID = 518113103  # Ваш Telegram ID

# Состояния для диалогов
(
    SELECT_PLAYER,
    SELECT_CATEGORY,
    SELECT_PLAYER2,
    NEW_VALUE,
    CONFIRM,
    SELECT_CATEGORY_SWAP,
    SELECT_CATEGORY_SHUFFLE,
    SELECT_CATEGORY_ADDINFO,
) = range(8)

CATEGORIES = ["Биология", "Профессия", "Здоровье", "Хобби", "Багаж", "Факт", "Особое условие"]
MULTIPLE_CATEGORIES = ["Багаж", "Особое условие"]

CHARACTER_POOLS = {cat: [] for cat in CATEGORIES}

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ================== БАЗА ДАННЫХ ==================
def init_db():
    conn = sqlite3.connect("bunker.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS rooms (
        code TEXT PRIMARY KEY,
        created_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_active INTEGER DEFAULT 1
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS players (
        user_id INTEGER,
        room_code TEXT,
        nick TEXT,
        data TEXT,
        PRIMARY KEY (user_id, room_code)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS user_room (
        user_id INTEGER PRIMARY KEY,
        room_code TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS open_info (
        room_code TEXT,
        player_nick TEXT,
        category TEXT,
        value TEXT
    )""")
    conn.commit()
    conn.close()

def db_execute(query, args=(), fetchone=False, fetchall=False):
    conn = sqlite3.connect("bunker.db")
    c = conn.cursor()
    c.execute(query, args)
    if fetchone:
        res = c.fetchone()
    elif fetchall:
        res = c.fetchall()
    else:
        res = None
    conn.commit()
    conn.close()
    return res

# ================== ЗАГРУЗКА ДАННЫХ ИЗ GOOGLE SHEETS ==================
def load_character_pools():
    global CHARACTER_POOLS
    if not GOOGLE_SHEETS_CSV_URL:
        logger.warning("Ссылка на Google Sheets не задана, пулы останутся пустыми.")
        return False
    try:
        response = requests.get(GOOGLE_SHEETS_CSV_URL)
        response.encoding = "utf-8"
        f = StringIO(response.text)
        reader = csv.DictReader(f)
        pools = {cat: [] for cat in CATEGORIES}
        for row in reader:
            for cat in CATEGORIES:
                val = row.get(cat, "").strip()
                if val:
                    pools[cat].append(val)
        for cat in CATEGORIES:
            if not pools[cat]:
                logger.warning(f"Категория {cat} пуста!")
        CHARACTER_POOLS = pools
        logger.info("Данные успешно загружены из Google Sheets")
        return True
    except Exception as e:
        logger.error(f"Ошибка загрузки данных: {e}")
        return False

# ================== ДЕКОРАТОР АДМИНА ==================
def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        if update.effective_user.id != ADMIN_ID:
            await update.message.reply_text("⛔ Эта команда только для администратора.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

# ================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==================
def get_user_room(user_id):
    res = db_execute("SELECT room_code FROM user_room WHERE user_id = ?", (user_id,), fetchone=True)
    return res[0] if res else None

def set_user_room(user_id, room_code):
    db_execute("INSERT OR REPLACE INTO user_room (user_id, room_code) VALUES (?, ?)", (user_id, room_code))

def clear_user_room(user_id):
    db_execute("DELETE FROM user_room WHERE user_id = ?", (user_id,))

def room_exists(room_code):
    res = db_execute("SELECT code FROM rooms WHERE code = ? AND is_active = 1", (room_code,), fetchone=True)
    return res is not None

def get_players(room_code):
    rows = db_execute("SELECT nick FROM players WHERE room_code = ?", (room_code,), fetchall=True)
    return [r[0] for r in rows]

def get_player_data(room_code, nick):
    row = db_execute("SELECT data FROM players WHERE room_code = ? AND nick = ?", (room_code, nick), fetchone=True)
    if not row:
        return None
    return json.loads(row[0])

def save_player_data(room_code, nick, data):
    db_execute("UPDATE players SET data = ? WHERE room_code = ? AND nick = ?", (json.dumps(data, ensure_ascii=False), room_code, nick))

def generate_random_character():
    data = {}
    for cat in CATEGORIES:
        if cat in MULTIPLE_CATEGORIES:
            values = random.sample(CHARACTER_POOLS[cat], min(2, len(CHARACTER_POOLS[cat])))
            data[cat] = values
        else:
            data[cat] = [random.choice(CHARACTER_POOLS[cat])]
    return data

def add_open_info(room_code, player_nick, category, value):
    db_execute("INSERT INTO open_info (room_code, player_nick, category, value) VALUES (?, ?, ?, ?)",
               (room_code, player_nick, category, value))

def get_open_info(room_code):
    rows = db_execute("SELECT player_nick, category, value FROM open_info WHERE room_code = ?", (room_code,), fetchall=True)
    info = {}
    for nick, cat, val in rows:
        info.setdefault(nick, {}).setdefault(cat, []).append(val)
    return info

# ================== КОМАНДЫ ==================
async def start(update: Update, context: CallbackContext):
    await update.message.reply_text(
        "👋 Добро пожаловать в игру **Бункер**!\n\n"
        "📌 **Для игроков:**\n"
        "/room <код> – войти в комнату (или создать, если вы админ)\n"
        "/info – показать открытую информацию\n\n"
        "🔐 Команды администратора доступны по /admin"
    )

async def admin_help(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён.")
        return
    await update.message.reply_text(
        "🔧 **Команды администратора:**\n\n"
        "**Управление комнатой:**\n"
        "/createroom <код> – создать новую комнату\n"
        "/closeroom – закрыть текущую комнату (удалить все данные)\n"
        "/players – список игроков в текущей комнате\n"
        "/reload – перезагрузить данные из Google Sheets\n\n"
        "**Диалоговые команды (после ввода бот задаст вопросы):**\n"
        "/random – добавить игроку случайную карту из категории\n"
        "/change – изменить карту игрока (заменить все значения)\n"
        "/swap – обменять карты между двумя игроками (целиком)\n"
        "/shuffle – перемешать все карты категории между игроками\n"
        "/addinfo – открыть информацию игрока (добавить в /info)\n\n"
        "Пример диалога: `/random` → выбираете игрока → категорию → готово."
    )

@admin_only
async def createroom(update: Update, context: CallbackContext):
    args = context.args
    if not args:
        await update.message.reply_text("Укажите код комнаты, например: `/createroom abcd`")
        return
    code = args[0].lower()
    if room_exists(code):
        await update.message.reply_text("❌ Комната с таким кодом уже существует.")
        return
    db_execute("INSERT INTO rooms (code, created_by) VALUES (?, ?)", (code, ADMIN_ID))
    set_user_room(ADMIN_ID, code)
    await update.message.reply_text(f"✅ Комната `{code}` создана! Теперь вы в ней.\n"
                                    "Игроки могут заходить по команде `/room {code}`")

@admin_only
async def closeroom(update: Update, context: CallbackContext):
    room = get_user_room(ADMIN_ID)
    if not room:
        await update.message.reply_text("❌ Вы не находитесь в комнате.")
        return
    db_execute("DELETE FROM open_info WHERE room_code = ?", (room,))
    db_execute("DELETE FROM players WHERE room_code = ?", (room,))
    db_execute("DELETE FROM rooms WHERE code = ?", (room,))
    db_execute("DELETE FROM user_room WHERE room_code = ?", (room,))
    await update.message.reply_text(f"🚪 Комната `{room}` закрыта. Все данные удалены.")

@admin_only
async def players_list(update: Update, context: CallbackContext):
    room = get_user_room(ADMIN_ID)
    if not room:
        await update.message.reply_text("❌ Вы не в комнате.")
        return
    players = get_players(room)
    if not players:
        await update.message.reply_text("В комнате пока нет игроков.")
        return
    text = "**Игроки в комнате:**\n"
    for nick in players:
        text += f"• {nick}\n"
    await update.message.reply_text(text)

@admin_only
async def reload_data(update: Update, context: CallbackContext):
    await update.message.reply_text("⏳ Загружаю данные из Google Sheets...")
    if load_character_pools():
        await update.message.reply_text("✅ Данные обновлены.")
    else:
        await update.message.reply_text("❌ Ошибка загрузки. Проверьте ссылку.")

async def room_join(update: Update, context: CallbackContext):
    args = context.args
    if not args:
        await update.message.reply_text("Введите код комнаты: `/room код`")
        return ConversationHandler.END
    code = args[0].lower()
    if not room_exists(code):
        await update.message.reply_text("❌ Комната не найдена.")
        return ConversationHandler.END
    context.user_data["joining_room"] = code
    await update.message.reply_text("Введите ваше игровое имя (ник):")
    return "WAIT_NICK"

async def room_nick(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    nick = update.message.text.strip()
    code = context.user_data.get("joining_room")
    if not code:
        await update.message.reply_text("Ошибка, начните сначала: /room код")
        return ConversationHandler.END
    players = get_players(code)
    if nick in players:
        await update.message.reply_text("❌ Это имя уже занято. Попробуйте другое.")
        return "WAIT_NICK"
    char_data = generate_random_character()
    db_execute("INSERT INTO players (user_id, room_code, nick, data) VALUES (?, ?, ?, ?)",
               (user_id, code, nick, json.dumps(char_data, ensure_ascii=False)))
    set_user_room(user_id, code)
    await update.message.reply_text(f"✅ Вы вошли в комнату `{code}` под именем **{nick}**.\n"
                                    "Ваш персонаж создан. Используйте /info для просмотра открытой информации.")
    return ConversationHandler.END

async def cancel(update: Update, context: CallbackContext):
    await update.message.reply_text("Действие отменено.")
    return ConversationHandler.END

async def info(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    room = get_user_room(user_id)
    if not room:
        await update.message.reply_text("❌ Вы не в комнате. Войдите через /room код")
        return
    open_info = get_open_info(room)
    if not open_info:
        await update.message.reply_text("Пока ничего не открыто.")
        return
    text = "**📋 Открытая информация:**\n"
    for nick, cats in open_info.items():
        text += f"\n**{nick}:**\n"
        for cat, values in cats.items():
            vals = ", ".join(values)
            text += f"  {cat}: {vals}\n"
    await update.message.reply_text(text)

# ================== ДИАЛОГОВЫЕ АДМИНСКИЕ КОМАНДЫ ==================
@admin_only
async def random_start(update: Update, context: CallbackContext):
    room = get_user_room(ADMIN_ID)
    if not room:
        await update.message.reply_text("❌ Вы не в комнате.")
        return ConversationHandler.END
    players = get_players(room)
    if not players:
        await update.message.reply_text("В комнате нет игроков.")
        return ConversationHandler.END
    context.user_data["room"] = room
    context.user_data["players"] = players
    await update.message.reply_text("Введите имя игрока, которому хотите добавить случайную карту:")
    return SELECT_PLAYER

async def random_player(update: Update, context: CallbackContext):
    nick = update.message.text.strip()
    if nick not in context.user_data["players"]:
        await update.message.reply_text("❌ Игрок не найден. Попробуйте ещё раз:")
        return SELECT_PLAYER
    context.user_data["target_nick"] = nick
    keyboard = [[cat] for cat in CATEGORIES]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите категорию:", reply_markup=reply_markup)
    return SELECT_CATEGORY

async def random_category(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    category = query.data
    room = context.user_data["room"]
    nick = context.user_data["target_nick"]
    player_data = get_player_data(room, nick)
    if not player_data:
        await query.edit_message_text("Ошибка: игрок не найден.")
        return ConversationHandler.END
    if category not in CHARACTER_POOLS or not CHARACTER_POOLS[category]:
        await query.edit_message_text(f"Нет данных для категории {category}.")
        return ConversationHandler.END
    new_val = random.choice(CHARACTER_POOLS[category])
    if category in MULTIPLE_CATEGORIES:
        player_data[category].append(new_val)
    else:
        player_data[category] = [new_val]
    save_player_data(room, nick, player_data)
    await query.edit_message_text(f"✅ Игроку **{nick}** добавлена карта **{category}**: {new_val}")
    return ConversationHandler.END

@admin_only
async def change_start(update: Update, context: CallbackContext):
    room = get_user_room(ADMIN_ID)
    if not room:
        await update.message.reply_text("❌ Вы не в комнате.")
        return ConversationHandler.END
    players = get_players(room)
    if not players:
        await update.message.reply_text("В комнате нет игроков.")
        return ConversationHandler.END
    context.user_data["room"] = room
    context.user_data["players"] = players
    await update.message.reply_text("Введите имя игрока, которому хотите изменить карту:")
    return SELECT_PLAYER

async def change_player(update: Update, context: CallbackContext):
    nick = update.message.text.strip()
    if nick not in context.user_data["players"]:
        await update.message.reply_text("❌ Игрок не найден. Попробуйте ещё раз:")
        return SELECT_PLAYER
    context.user_data["target_nick"] = nick
    keyboard = [[cat] for cat in CATEGORIES]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите категорию для изменения:", reply_markup=reply_markup)
    return SELECT_CATEGORY

async def change_category(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    category = query.data
    context.user_data["category"] = category
    await query.edit_message_text(f"Введите новое значение для категории **{category}**:")
    return NEW_VALUE

async def change_value(update: Update, context: CallbackContext):
    new_val = update.message.text.strip()
    room = context.user_data["room"]
    nick = context.user_data["target_nick"]
    category = context.user_data["category"]
    player_data = get_player_data(room, nick)
    if not player_data:
        await update.message.reply_text("Ошибка: игрок не найден.")
        return ConversationHandler.END
    if category in MULTIPLE_CATEGORIES:
        player_data[category] = [new_val]
    else:
        player_data[category] = [new_val]
    save_player_data(room, nick, player_data)
    await update.message.reply_text(f"✅ Игроку **{nick}** изменена категория **{category}** на: {new_val}")
    return ConversationHandler.END

@admin_only
async def swap_start(update: Update, context: CallbackContext):
    room = get_user_room(ADMIN_ID)
    if not room:
        await update.message.reply_text("❌ Вы не в комнате.")
        return ConversationHandler.END
    players = get_players(room)
    if len(players) < 2:
        await update.message.reply_text("Нужно минимум 2 игрока для обмена.")
        return ConversationHandler.END
    context.user_data["room"] = room
    context.user_data["players"] = players
    await update.message.reply_text("Введите имя **первого** игрока:")
    return SELECT_PLAYER

async def swap_player1(update: Update, context: CallbackContext):
    nick1 = update.message.text.strip()
    if nick1 not in context.user_data["players"]:
        await update.message.reply_text("❌ Игрок не найден. Попробуйте ещё раз:")
        return SELECT_PLAYER
    context.user_data["nick1"] = nick1
    await update.message.reply_text("Введите имя **второго** игрока:")
    return SELECT_PLAYER2

async def swap_player2(update: Update, context: CallbackContext):
    nick2 = update.message.text.strip()
    if nick2 not in context.user_data["players"]:
        await update.message.reply_text("❌ Игрок не найден. Попробуйте ещё раз:")
        return SELECT_PLAYER2
    if nick2 == context.user_data["nick1"]:
        await update.message.reply_text("❌ Игроки должны быть разными. Введите другое имя:")
        return SELECT_PLAYER2
    context.user_data["nick2"] = nick2
    keyboard = [[cat] for cat in CATEGORIES]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите категорию для обмена:", reply_markup=reply_markup)
    return SELECT_CATEGORY_SWAP

async def swap_category(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    category = query.data
    room = context.user_data["room"]
    nick1 = context.user_data["nick1"]
    nick2 = context.user_data["nick2"]
    data1 = get_player_data(room, nick1)
    data2 = get_player_data(room, nick2)
    if not data1 or not data2:
        await query.edit_message_text("Ошибка получения данных игроков.")
        return ConversationHandler.END
    data1[category], data2[category] = data2[category], data1[category]
    save_player_data(room, nick1, data1)
    save_player_data(room, nick2, data2)
    await query.edit_message_text(f"✅ Категория **{category}** обменяна между **{nick1}** и **{nick2}**.")
    return ConversationHandler.END

@admin_only
async def shuffle_start(update: Update, context: CallbackContext):
    room = get_user_room(ADMIN_ID)
    if not room:
        await update.message.reply_text("❌ Вы не в комнате.")
        return ConversationHandler.END
    players = get_players(room)
    if len(players) < 2:
        await update.message.reply_text("Нужно минимум 2 игрока для перемешивания.")
        return ConversationHandler.END
    context.user_data["room"] = room
    context.user_data["players"] = players
    keyboard = [[cat] for cat in CATEGORIES]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите категорию для перемешивания:", reply_markup=reply_markup)
    return SELECT_CATEGORY_SHUFFLE

async def shuffle_category(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    category = query.data
    room = context.user_data["room"]
    players = get_players(room)
    all_values = []
    player_values = {}
    for nick in players:
        data = get_player_data(room, nick)
        if data and category in data:
            vals = data[category]
            player_values[nick] = vals
            all_values.extend(vals)
    if not all_values:
        await query.edit_message_text("Нет значений для перемешивания.")
        return ConversationHandler.END
    random.shuffle(all_values)
    new_values = {}
    idx = 0
    for nick, vals in player_values.items():
        count = len(vals)
        new_vals = all_values[idx:idx+count]
        idx += count
        new_values[nick] = new_vals
    if idx < len(all_values):
        remaining = all_values[idx:]
        first_nick = list(player_values.keys())[0]
        new_values[first_nick].extend(remaining)
    for nick, vals in new_values.items():
        data = get_player_data(room, nick)
        data[category] = vals
        save_player_data(room, nick, data)
    await query.edit_message_text(f"✅ Категория **{category}** перемешана между игроками.")
    return ConversationHandler.END

@admin_only
async def addinfo_start(update: Update, context: CallbackContext):
    room = get_user_room(ADMIN_ID)
    if not room:
        await update.message.reply_text("❌ Вы не в комнате.")
        return ConversationHandler.END
    players = get_players(room)
    if not players:
        await update.message.reply_text("В комнате нет игроков.")
        return ConversationHandler.END
    context.user_data["room"] = room
    context.user_data["players"] = players
    await update.message.reply_text("Введите имя игрока, информацию которого хотите открыть:")
    return SELECT_PLAYER

async def addinfo_player(update: Update, context: CallbackContext):
    nick = update.message.text.strip()
    if nick not in context.user_data["players"]:
        await update.message.reply_text("❌ Игрок не найден. Попробуйте ещё раз:")
        return SELECT_PLAYER
    context.user_data["target_nick"] = nick
    keyboard = [[cat] for cat in CATEGORIES]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите категорию для открытия:", reply_markup=reply_markup)
    return SELECT_CATEGORY_ADDINFO

async def addinfo_category(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    category = query.data
    room = context.user_data["room"]
    nick = context.user_data["target_nick"]
    player_data = get_player_data(room, nick)
    if not player_data or category not in player_data:
        await query.edit_message_text("У игрока нет такой категории.")
        return ConversationHandler.END
    values = player_data[category]
    for val in values:
        add_open_info(room, nick, category, val)
    await query.edit_message_text(f"✅ Информация игрока **{nick}** по категории **{category}** открыта: {', '.join(values)}")
    return ConversationHandler.END

# ================== НАСТРОЙКА FLASK ДЛЯ RENDER ==================
app = Flask(__name__)

@app.route('/')
def index():
    return jsonify({
        "status": "running",
        "bot": "Bunker Bot",
        "message": "Send commands to your Telegram bot"
    })

@app.route('/health')
def health():
    return "OK", 200

# ================== ЗАПУСК БОТА В ФОНОВОМ ПОТОКЕ ==================
def start_bot():
    print("🚀 Запуск Telegram бота в фоновом потоке...", flush=True)
    try:
        # Создаём цикл событий для этого потока
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        init_db()
        load_character_pools()

        application = Application.builder().token(TELEGRAM_TOKEN).build()

        # Обычные команды
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("admin", admin_help))
        application.add_handler(CommandHandler("info", info))
        application.add_handler(CommandHandler("createroom", createroom))
        application.add_handler(CommandHandler("closeroom", closeroom))
        application.add_handler(CommandHandler("players", players_list))
        application.add_handler(CommandHandler("reload", reload_data))

        # Диалог входа в комнату
        room_conv = ConversationHandler(
            entry_points=[CommandHandler("room", room_join)],
            states={
                "WAIT_NICK": [MessageHandler(filters.TEXT & ~filters.COMMAND, room_nick)],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )
        application.add_handler(room_conv)

        # Админские диалоги
        random_conv = ConversationHandler(
            entry_points=[CommandHandler("random", random_start)],
            states={
                SELECT_PLAYER: [MessageHandler(filters.TEXT & ~filters.COMMAND, random_player)],
                SELECT_CATEGORY: [CallbackQueryHandler(random_category)],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )
        application.add_handler(random_conv)

        change_conv = ConversationHandler(
            entry_points=[CommandHandler("change", change_start)],
            states={
                SELECT_PLAYER: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_player)],
                SELECT_CATEGORY: [CallbackQueryHandler(change_category)],
                NEW_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_value)],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )
        application.add_handler(change_conv)

        swap_conv = ConversationHandler(
            entry_points=[CommandHandler("swap", swap_start)],
            states={
                SELECT_PLAYER: [MessageHandler(filters.TEXT & ~filters.COMMAND, swap_player1)],
                SELECT_PLAYER2: [MessageHandler(filters.TEXT & ~filters.COMMAND, swap_player2)],
                SELECT_CATEGORY_SWAP: [CallbackQueryHandler(swap_category)],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )
        application.add_handler(swap_conv)

        shuffle_conv = ConversationHandler(
            entry_points=[CommandHandler("shuffle", shuffle_start)],
            states={
                SELECT_CATEGORY_SHUFFLE: [CallbackQueryHandler(shuffle_category)],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )
        application.add_handler(shuffle_conv)

        addinfo_conv = ConversationHandler(
            entry_points=[CommandHandler("addinfo", addinfo_start)],
            states={
                SELECT_PLAYER: [MessageHandler(filters.TEXT & ~filters.COMMAND, addinfo_player)],
                SELECT_CATEGORY_ADDINFO: [CallbackQueryHandler(addinfo_category)],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )
        application.add_handler(addinfo_conv)

        print("✅ Бот успешно запущен и готов к работе!", flush=True)
        # Запускаем polling без обработчиков сигналов (т.к. мы в фоновом потоке)
        application.run_polling(stop_signals=None)
    except Exception as e:
        print(f"❌ КРИТИЧЕСКАЯ ОШИБКА В БОТЕ: {e}", flush=True)
        traceback.print_exc()

# Запускаем бота в отдельном потоке сразу при импорте
bot_thread = threading.Thread(target=start_bot, daemon=True)
bot_thread.start()
print("🚀 Фоновый поток с ботом запущен", flush=True)

# Для локального запуска (не на Render)
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
