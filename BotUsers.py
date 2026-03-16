"""
BotUsers.py — автоматический учёт пользователей бота.
Хранит {user_id: {username, chat_id, first_seen, last_seen}} в users.json.
Рассылка идёт по chat_id (в личных чатах совпадает с user_id).
"""

import os
import json
from datetime import datetime
from typing import Dict, List

_USERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")


def _load() -> Dict[str, dict]:
    if os.path.exists(_USERS_FILE):
        try:
            with open(_USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save(data: Dict[str, dict]):
    with open(_USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def register(user_id: int, chat_id: int = None, username: str = ""):
    """
    Регистрирует пользователя. Обновляет last_seen, username и chat_id.
    chat_id используется для рассылок (в личных чатах = user_id).
    """
    data = _load()
    key  = str(user_id)
    now  = datetime.utcnow().isoformat() + "Z"
    # chat_id по умолчанию = user_id если не передан
    effective_chat_id = chat_id if chat_id is not None else user_id
    if key not in data:
        data[key] = {
            "username":   username,
            "chat_id":    effective_chat_id,
            "first_seen": now,
            "last_seen":  now,
        }
    else:
        data[key]["last_seen"] = now
        data[key]["chat_id"]   = effective_chat_id
        if username:
            data[key]["username"] = username
    _save(data)


def get_all_ids() -> List[int]:
    """Возвращает список chat_id для рассылок."""
    return [info.get("chat_id", int(uid)) for uid, info in _load().items()]


def get_all() -> Dict[str, dict]:
    return _load()