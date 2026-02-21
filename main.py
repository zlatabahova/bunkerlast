import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web
import asyncpg

from config import BOT_TOKEN, WEBHOOK_URL, WEBHOOK_PATH, WEBAPP_HOST, WEBAPP_PORT, SPREADSHEET_ID
from db import create_pool, init_db, pool as db_pool_global
from google_sheets import load_from_sheets, update_pool
from handlers import common, room, player, info, admin_actions

import sys
import traceback

print("=== STARTING BOT ===", file=sys.stderr)
sys.stderr.flush()

logging.basicConfig(level=logging.INFO)

async def on_startup(bot: Bot, db_pool: asyncpg.Pool):
    await init_db(db_pool)
    # Загрузка данных из Google Sheets
    try:
        categories = await load_from_sheets(SPREADSHEET_ID)
        async with db_pool.acquire() as conn:
            await update_pool(conn, categories)
        admin_actions.pool_cache = categories
        logging.info("Google Sheets data loaded")
    except Exception as e:
        logging.error(f"Failed to load sheets: {e}")
    await bot.set_webhook(WEBHOOK_URL + WEBHOOK_PATH)

async def on_shutdown(bot: Bot):
    await bot.delete_webhook()

async def handle_webhook(request):
    update = types.Update(**await request.json())
    await dp.feed_update(bot, update)
    return web.Response()

def main():
    app = web.Application()
    app.router.add_post(WEBHOOK_PATH, handle_webhook)

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    dp.include_router(common.router)
    dp.include_router(room.router)
    dp.include_router(player.router)
    dp.include_router(info.router)
    dp.include_router(admin_actions.router)

    # Передаём пул в глобальную переменную для доступа из хендлеров
    async def init_pool():
        global db_pool_global
        db_pool_global = await create_pool()
        return db_pool_global

    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_pool())

    # Запуск aiohttp приложения
    web.run_app(app, host=WEBAPP_HOST, port=WEBAPP_PORT)

if __name__ == "__main__":
    main()
