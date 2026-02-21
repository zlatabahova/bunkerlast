import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from config import SPREADSHEET_ID, CREDENTIALS_INFO

SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']

def get_service():
    if CREDENTIALS_INFO is None:
        raise Exception("GOOGLE_SHEETS_CREDENTIALS not set or invalid")
    creds = service_account.Credentials.from_service_account_info(CREDENTIALS_INFO, scopes=SCOPES)
    service = build('sheets', 'v4', credentials=creds)
    return service

async def load_from_sheets(spreadsheet_id, range_name="Персонажи!A:I"):
    service = get_service()
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()
    values = result.get('values', [])
    if not values:
        return {}
    header = values[0]  # заголовки
    rows = values[1:]   # данные
    # Ожидаем колонки: Биология, Профессия, Здоровье, Хобби, Багаж1, Багаж2, Факт, Особое условие1, Особое условие2
    categories = {
        'bio': [], 'prof': [], 'health': [], 'hobby': [],
        'luggage': [], 'fact': [], 'special': []
    }
    for row in rows:
        # Заполняем, если ячейка не пуста
        if len(row) > 0 and row[0]:
            categories['bio'].append(row[0])
        if len(row) > 1 and row[1]:
            categories['prof'].append(row[1])
        if len(row) > 2 and row[2]:
            categories['health'].append(row[2])
        if len(row) > 3 and row[3]:
            categories['hobby'].append(row[3])
        if len(row) > 4 and row[4]:
            categories['luggage'].append(row[4])
        if len(row) > 5 and row[5]:
            categories['luggage'].append(row[5])   # багаж2 тоже в luggage
        if len(row) > 6 and row[6]:
            categories['fact'].append(row[6])
        if len(row) > 7 and row[7]:
            categories['special'].append(row[7])
        if len(row) > 8 and row[8]:
            categories['special'].append(row[8])
    return categories

async def update_pool(conn, categories):
    # Очищаем старый пул и заполняем новым
    await conn.execute("DELETE FROM pool")
    for cat, values in categories.items():
        for val in values:
            await conn.execute("INSERT INTO pool (category, value) VALUES ($1, $2) ON CONFLICT DO NOTHING", cat, val)
