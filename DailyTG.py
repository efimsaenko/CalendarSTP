"""
DailyTG.py — точка входа Telegram-бота.

config.txt:
    BOT_TOKEN=...
    ADMIN_CHAT_ID=123456789,987654321   ← можно несколько через запятую
    USER_LIMIT=10
"""

import asyncio
import os
import signal
import sys
from functools import partial

from aiogram import Bot, Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.asyncio import AsyncIOExecutor

from logger import get_logger
from BotHandlers import register_handlers, scheduled_daily, scheduled_19th, scheduled_5th


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(path: str = "config.txt") -> dict:
    if not os.path.exists(path):
        raise RuntimeError(f"Файл конфигурации не найден: {path}")
    cfg = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg


config    = load_config()
BOT_TOKEN = config.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан в config.txt")

# Поддержка нескольких админов: ADMIN_CHAT_ID=123,456
_raw_admins  = config.get("ADMIN_CHAT_ID", "")
ADMIN_IDS    = [int(x.strip()) for x in _raw_admins.split(",") if x.strip().isdigit()]
if not ADMIN_IDS:
    raise RuntimeError("ADMIN_CHAT_ID не задан в config.txt")

# Обновляем config чтобы BotHandlers видел список
config["ADMIN_IDS"] = ADMIN_IDS

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
LOCK_FILE = os.path.join(BASE_DIR, "bot.lock")
logger    = get_logger("DailyTG")

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher()

# coalesce=True       — несколько пропущенных запусков объединяются в один
# misfire_grace_time=None — задача выполнится даже если бот был выключен
scheduler = AsyncIOScheduler(
    jobstores={"default": MemoryJobStore()},
    executors={"default": AsyncIOExecutor()},
    job_defaults={"coalesce": True, "misfire_grace_time": None},
)


# ---------------------------------------------------------------------------
# Single-instance lock
# ---------------------------------------------------------------------------

def acquire_lock():
    if os.path.exists(LOCK_FILE):
        with open(LOCK_FILE) as f:
            old_pid = f.read().strip()
        logger.warning(f"Lock найден (PID {old_pid}), проверяем процесс...")
        try:
            os.kill(int(old_pid), 0)
            logger.error(f"Бот уже запущен (PID {old_pid}). Выходим.")
            sys.exit(1)
        except (OSError, ValueError):
            logger.warning("Старый процесс мёртв, удаляем lock.")
            os.remove(LOCK_FILE)
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))
    logger.info(f"Lock создан (PID {os.getpid()})")


def release_lock():
    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)
        logger.info("Lock удалён")


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------

async def shutdown():
    logger.info("Shutdown started")
    release_lock()
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        pass
    try:
        await bot.session.close()
    except Exception:
        pass
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("Shutdown complete")


def install_signals():
    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
    except (RuntimeError, NotImplementedError):
        pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    install_signals()
    register_handlers(dp, bot, config)

    scheduler.add_job(
        partial(scheduled_daily, bot, config),
        "cron", hour=9, minute=0,
        id="daily", replace_existing=True,
    )
    scheduler.add_job(
        partial(scheduled_19th, bot, config),
        "cron", day=19, hour=9, minute=0,
        id="monthly_19th", replace_existing=True,
    )
    scheduler.add_job(
        partial(scheduled_5th, bot, config),
        "cron", day=5, hour=9, minute=0,
        id="monthly_5th", replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler started: daily@9:00, 19th@9:00, 5th@9:00")
    await dp.start_polling(bot)


if __name__ == "__main__":
    acquire_lock()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Остановлен вручную")
    finally:
        release_lock()