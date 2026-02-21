import asyncpg
from config import DATABASE_URL

# Глобальная переменная для пула соединений
pool = None

async def create_pool():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)
    return pool

async def init_db(pool):
    async with pool.acquire() as conn:
        # Таблица комнат
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS rooms (
                code TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT NOW(),
                is_active BOOLEAN DEFAULT TRUE
            )
        ''')
        # Таблица игроков
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS players (
                user_id BIGINT,
                room_code TEXT REFERENCES rooms(code) ON DELETE CASCADE,
                username TEXT,
                name TEXT,
                bio TEXT,
                prof TEXT,
                health TEXT,
                hobby TEXT,
                luggage1 TEXT,
                luggage2 TEXT,
                fact TEXT,
                special1 TEXT,
                special2 TEXT,
                used_special1 BOOLEAN DEFAULT FALSE,
                used_special2 BOOLEAN DEFAULT FALSE,
                revealed TEXT[] DEFAULT '{}',
                PRIMARY KEY (user_id, room_code)
            )
        ''')
        # Таблица пула значений из Google Sheets
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS pool (
                id SERIAL PRIMARY KEY,
                category TEXT,
                value TEXT,
                UNIQUE(category, value)
            )
        ''')
