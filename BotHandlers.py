"""
BotHandlers.py — хэндлеры команд бота и scheduled jobs.
"""

import asyncio
import uuid
import os
from collections import defaultdict
from datetime import datetime
from typing import Optional, List

import pandas as pd
from aiogram import Bot, Dispatcher, types

from logger import get_logger
import BotUsers
import DailyPipeline
from MonthPipeline import (
    run_month_pipeline,
    get_calendar_path,
    format_changes_message,
)

logger   = get_logger("BotHandlers")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_user_requests: defaultdict[int, int] = defaultdict(int)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gen_id() -> str:
    return uuid.uuid4().hex[:12]


def _get_admin_ids(config: dict) -> List[int]:
    if "ADMIN_IDS" in config:
        return config["ADMIN_IDS"]
    raw = config.get("ADMIN_CHAT_ID", "")
    return [int(x.strip()) for x in str(raw).split(",") if x.strip().isdigit()]


def _is_admin(user_id: int, config: dict) -> bool:
    return user_id in _get_admin_ids(config)


def _check_limit(user_id: int, config: dict, limit: int) -> bool:
    if _is_admin(user_id, config):
        return True
    if _user_requests[user_id] >= limit:
        return False
    _user_requests[user_id] += 1
    return True


def _user_info(msg: types.Message) -> dict:
    return {"user_id": msg.from_user.id, "username": msg.from_user.username or ""}


async def _run_daily(date_str: str, force_grab: bool = False,
                     user_info: Optional[dict] = None) -> str:
    req_id = _gen_id()
    return await asyncio.to_thread(
        DailyPipeline.run, date_str, req_id, force_grab, user_info
    )


async def _run_month(month_str: str, force_grab: bool = False) -> dict:
    return await asyncio.to_thread(
        run_month_pipeline, month_str, BASE_DIR, force_grab
    )


async def _send_with_retry(
    bot: Bot,
    chat_id: int,
    text: Optional[str] = None,
    document_path: Optional[str] = None,
    caption: Optional[str] = None,
    retries: int = 3,
    delay: float = 10.0,
):
    """Отправляет сообщение или документ с повторными попытками при сетевой ошибке."""
    for attempt in range(1, retries + 1):
        try:
            if document_path:
                await bot.send_document(
                    chat_id, types.FSInputFile(document_path), caption=caption
                )
            else:
                await bot.send_message(chat_id, text, parse_mode="HTML")
            return
        except Exception as e:
            if attempt < retries:
                logger.warning(
                    f"Попытка {attempt}/{retries} для {chat_id} не удалась: {e}. "
                    f"Повтор через {delay}с"
                )
                await asyncio.sleep(delay)
            else:
                logger.error(f"Все {retries} попытки исчерпаны для {chat_id}: {e}")


async def _broadcast_text(bot: Bot, text: str):
    """Рассылает текст всем пользователям с retry."""
    for uid in BotUsers.get_all_ids():
        await _send_with_retry(bot, uid, text=text)


async def _broadcast_document(bot: Bot, path: str, caption: str,
                               extra_text: str = ""):
    """Рассылает документ всем пользователям с retry."""
    for uid in BotUsers.get_all_ids():
        if extra_text:
            await _send_with_retry(bot, uid, text=extra_text)
        await _send_with_retry(bot, uid, document_path=path, caption=caption)


# ---------------------------------------------------------------------------
# Middleware: авторегистрация пользователей
# ---------------------------------------------------------------------------

class _RegisterMiddleware:
    """Регистрирует каждого пользователя при любом входящем сообщении."""
    async def __call__(self, handler, event: types.Message, data: dict):
        try:
            BotUsers.register(
                user_id=event.from_user.id,
                chat_id=event.chat.id,
                username=event.from_user.username or "",
            )
        except Exception:
            pass
        return await handler(event, data)


# ---------------------------------------------------------------------------
# Команды бота
# ---------------------------------------------------------------------------

def register_handlers(dp: Dispatcher, bot: Bot, config: dict):
    limit = int(config.get("USER_LIMIT", 10))

    dp.message.middleware(_RegisterMiddleware())

    # /today
    @dp.message(lambda m: m.text and m.text.startswith("/today"))
    async def today(msg: types.Message):
        if not _check_limit(msg.from_user.id, config, limit):
            return await msg.answer("Лимит запросов исчерпан")
        await msg.answer("Запуск...")
        text = await _run_daily(
            datetime.now().strftime("%Y-%m-%d"),
            user_info=_user_info(msg),
        )
        await msg.answer(text, parse_mode="HTML")

    # /date 07.03.2026
    @dp.message(lambda m: m.text and m.text.startswith("/date"))
    async def by_date(msg: types.Message):
        if not _check_limit(msg.from_user.id, config, limit):
            return await msg.answer("Лимит запросов исчерпан")
        parts = msg.text.strip().split()
        if len(parts) != 2:
            return await msg.answer("Формат: /date 07.03.2026")
        try:
            date_str = datetime.strptime(parts[1], "%d.%m.%Y").strftime("%Y-%m-%d")
        except ValueError:
            return await msg.answer("Неверный формат даты. Используй 07.03.2026")
        await msg.answer(f"Запуск за {parts[1]}...")
        text = await _run_daily(date_str, user_info=_user_info(msg))
        await msg.answer(text, parse_mode="HTML")

    # /month 03.2026
    @dp.message(lambda m: m.text and m.text.startswith("/month"))
    async def by_month(msg: types.Message):
        if not _check_limit(msg.from_user.id, config, limit):
            return await msg.answer("Лимит запросов исчерпан")
        parts = msg.text.strip().split()
        if len(parts) != 2:
            return await msg.answer("Формат: /month 03.2026")
        month_str = parts[1].strip()
        try:
            datetime.strptime(month_str, "%m.%Y")
        except ValueError:
            return await msg.answer("Неверный формат. Используй MM.YYYY")
        existing = get_calendar_path(month_str, BASE_DIR)
        if existing:
            await msg.answer(f"📅 Календарь {month_str} уже готов, отправляю...")
            return await msg.answer_document(
                types.FSInputFile(existing), caption=f"Календарь {month_str}"
            )
        await msg.answer(f"⏳ Собираю {month_str}, подождите...")
        result = await _run_month(month_str)
        if result["status"] == "ok":
            await msg.answer_document(
                types.FSInputFile(result["calendar_path"]),
                caption=f"✅ Календарь {month_str} готов",
            )
        else:
            await msg.answer(f"❌ Ошибка: {result.get('error', '')}")

    # /delete 07.03.2026  (admin)
    @dp.message(lambda m: m.text and m.text.startswith("/delete "))
    async def delete_day(msg: types.Message):
        if not _is_admin(msg.from_user.id, config):
            return await msg.answer("Доступ запрещён")
        parts = msg.text.strip().split()
        if len(parts) != 2:
            return await msg.answer("Формат: /delete 07.03.2026")
        try:
            date_str = datetime.strptime(parts[1], "%d.%m.%Y").strftime("%Y-%m-%d")
        except ValueError:
            return await msg.answer("Неверный формат даты")
        _, _, filtered_csv = DailyPipeline.get_date_paths(date_str)
        if os.path.exists(filtered_csv):
            os.remove(filtered_csv)
            await msg.answer(f"✅ Удалён: {filtered_csv}")
        else:
            await msg.answer("Файл не найден")

    # /deleteMonth 03.2026  (admin)
    @dp.message(lambda m: m.text and m.text.startswith("/deleteMonth"))
    async def delete_month(msg: types.Message):
        if not _is_admin(msg.from_user.id, config):
            return await msg.answer("Доступ запрещён")
        parts = msg.text.strip().split()
        if len(parts) != 2:
            return await msg.answer("Формат: /deleteMonth 03.2026")
        month_str = parts[1].strip()
        try:
            datetime.strptime(month_str, "%m.%Y")
        except ValueError:
            return await msg.answer("Неверный формат. Используй MM.YYYY")
        cal = get_calendar_path(month_str, BASE_DIR)
        if cal and os.path.exists(cal):
            os.remove(cal)
            await msg.answer(f"✅ Удалён: {cal}\nПри /month {month_str} пересоберётся.")
        else:
            await msg.answer(f"Файл за {month_str} не найден")

    # /add Full / Short / Color / Escalation  (admin)
    @dp.message(lambda m: m.text and m.text.startswith("/add"))
    async def add_tournament(msg: types.Message):
        if not _is_admin(msg.from_user.id, config):
            return await msg.answer("Доступ запрещён")
        payload = msg.text[len("/add"):].strip()
        parts   = [p.strip() for p in payload.split("/") if p.strip()]
        if len(parts) < 2:
            return await msg.answer(
                "Формат: /add Full / Short / Color / Escalation\n"
                "Пример: /add Кубок Англии. / Кубок Англии / Зеленый / 0"
            )
        full, short = parts[0], parts[1]
        color      = parts[2] if len(parts) >= 3 else ""
        escalation = parts[3] if len(parts) >= 4 else "0"
        if escalation not in ("0", "1"):
            escalation = "0"

        TOURNAMENTS_PATH = DailyPipeline.TOURNAMENTS_PATH
        if not os.path.exists(TOURNAMENTS_PATH):
            with open(TOURNAMENTS_PATH, "w", encoding="utf-8") as f:
                f.write("tournament;short;importants;escalation\n")

        df = pd.read_csv(TOURNAMENTS_PATH, sep=";", dtype=str)
        df.columns = [c.strip().lower() for c in df.columns]
        name_col = "tournament" if "tournament" in df.columns else df.columns[0]
        if full.strip().lower() in df[name_col].str.strip().str.lower().tolist():
            return await msg.answer(f"Турнир уже существует: {full}")

        with open(TOURNAMENTS_PATH, "a", encoding="utf-8", newline="") as f:
            f.write(f"\n{full};{short};{color};{escalation}")

        logger.info(f"Added: {full!r} / {short!r}", extra={"user_id": msg.from_user.id})
        await msg.answer(
            f"✅ Добавлен:\n<b>{full}</b> → {short} [{color}] escalation={escalation}",
            parse_mode="HTML",
        )

    # /users  (admin)
    @dp.message(lambda m: m.text and m.text.strip() == "/users")
    async def list_users(msg: types.Message):
        if not _is_admin(msg.from_user.id, config):
            return await msg.answer("Доступ запрещён")
        all_users = BotUsers.get_all()
        if not all_users:
            return await msg.answer("Пользователей пока нет")
        lines = [f"👥 Пользователей: {len(all_users)}\n"]
        for uid, info in all_users.items():
            uname   = f"@{info['username']}" if info.get("username") else "—"
            chat_id = info.get("chat_id", uid)
            lines.append(
                f"  user_id={uid}  chat_id={chat_id}  {uname}"
                f"  (был: {info.get('last_seen', '')})"
            )
        await msg.answer("\n".join(lines))


# ---------------------------------------------------------------------------
# Scheduled jobs
# ---------------------------------------------------------------------------

async def scheduled_daily(bot: Bot, config: dict):
    """Ежедневная рассылка в 9:00."""
    req_id   = _gen_id()
    date_str = datetime.now().strftime("%Y-%m-%d")
    logger.info("scheduled_daily triggered", extra={"request_id": req_id})
    try:
        text = await _run_daily(
            date_str, force_grab=True,
            user_info={"user_id": _get_admin_ids(config)[0], "username": "scheduler"},
        )
        await _broadcast_text(bot, text)
        logger.info("scheduled_daily done", extra={"request_id": req_id})
    except Exception:
        logger.exception("scheduled_daily error", extra={"request_id": req_id})
        for admin_id in _get_admin_ids(config):
            await _send_with_retry(
                bot, admin_id,
                text="⚠️ Ошибка daily job — смотри логи",
                retries=5, delay=30.0,
            )


async def scheduled_19th(bot: Bot, config: dict):
    """19-го: собираем следующий месяц и рассылаем."""
    req_id    = _gen_id()
    now       = datetime.now()
    nm        = now.month % 12 + 1
    ny        = now.year + (1 if now.month == 12 else 0)
    month_str = f"{nm:02d}.{ny}"
    logger.info(f"scheduled_19th: {month_str}", extra={"request_id": req_id})
    try:
        result = await _run_month(month_str)
        if result["status"] == "ok":
            await _broadcast_document(
                bot, result["calendar_path"],
                caption=f"📅 Предварительный календарь {month_str}",
            )
        else:
            for admin_id in _get_admin_ids(config):
                await _send_with_retry(
                    bot, admin_id,
                    text=f"⚠️ Ошибка сборки {month_str}: {result.get('error', '')}",
                )
    except Exception:
        logger.exception("scheduled_19th error", extra={"request_id": req_id})


async def scheduled_5th(bot: Bot, config: dict):
    """5-го: обновляем текущий месяц, рассылаем diff."""
    req_id    = _gen_id()
    month_str = datetime.now().strftime("%m.%Y")
    logger.info(f"scheduled_5th: {month_str}", extra={"request_id": req_id})
    try:
        result = await _run_month(month_str, force_grab=True)
        if result["status"] == "ok":
            extra = format_changes_message(result.get("changed", {}), month_str)
            await _broadcast_document(
                bot, result["calendar_path"],
                caption=f"🔄 Обновлённый календарь {month_str}",
                extra_text=extra,
            )
        else:
            for admin_id in _get_admin_ids(config):
                await _send_with_retry(
                    bot, admin_id,
                    text=f"⚠️ Ошибка обновления {month_str}: {result.get('error', '')}",
                )
    except Exception:
        logger.exception("scheduled_5th error", extra={"request_id": req_id})