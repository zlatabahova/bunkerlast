import random
import string
from typing import List, Dict

def generate_room_code(length=4):
    return ''.join(random.choices(string.ascii_uppercase, k=length))

def get_random_unique_values(pool: List[str], exclude: List[str], count: int = 1) -> List[str]:
    available = [v for v in pool if v not in exclude]
    if len(available) < count:
        raise ValueError(f"Недостаточно уникальных значений в пуле. Требуется {count}, доступно {len(available)}")
    return random.sample(available, count)

def shuffle_luggage(players: List[Dict]) -> List[Dict]:
    # Собираем все багажи
    all_luggage = []
    for p in players:
        all_luggage.append(p['luggage1'])
        all_luggage.append(p['luggage2'])
    random.shuffle(all_luggage)
    # Раздаём по два
    new_players = []
    for i, p in enumerate(players):
        p['luggage1'] = all_luggage[2*i]
        p['luggage2'] = all_luggage[2*i+1]
        new_players.append(p)
    return new_players
