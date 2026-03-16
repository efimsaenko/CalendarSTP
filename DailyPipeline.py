"""
DailyPipeline.py — синхронный пайплайн за один день.
Импортируется в DailyTG.py и запускается через asyncio.to_thread.
"""

import os
import csv
import logging
from datetime import datetime
from typing import List

import pandas as pd

from logger import get_logger
from DailyGrabber import ChampionatGrabber
from DailyFilter import filter_matches_by_tournaments, load_tournaments
from DailyOutput import format_output, collect_tournament_names, load_short_names

logger = get_logger("DailyPipeline")

BASE_DIR         = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT        = os.path.join(BASE_DIR, "data")
TOURNAMENTS_PATH = os.path.join(BASE_DIR, "tournaments.csv")


def get_date_paths(date_str: str) -> tuple[str, str, str]:
    """Возвращает (date_dir, matches_csv, filtered_csv) для даты YYYY-MM-DD."""
    dt    = datetime.strptime(date_str, "%Y-%m-%d")
    folder = os.path.join(DATA_ROOT, dt.strftime("%Y"), dt.strftime("%m"))
    os.makedirs(folder, exist_ok=True)
    return (
        folder,
        os.path.join(folder, f"matches_{date_str}.csv"),
        os.path.join(folder, f"filtered_{date_str}.csv"),
    )


def _write_csv(matches: List[dict], path: str):
    if not matches:
        return
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(matches[0].keys()))
        writer.writeheader()
        writer.writerows(matches)
    os.replace(tmp, path)


def run(date_str: str, request_id: str, force_grab: bool = False,
        user_info: dict = None) -> str:
    """
    Полный пайплайн за один день.
    Возвращает отформатированный текст для Telegram (HTML).
    """
    uid   = user_info.get("user_id")  if user_info else None
    uname = user_info.get("username") if user_info else None
    logger.info(f"pipeline start {date_str} force={force_grab}",
                extra={"request_id": request_id, "user_id": uid, "username": uname})

    date_dir, matches_csv, filtered_csv = get_date_paths(date_str)

    # Пробуем взять кэш отфильтрованного
    filtered_df = None
    if not force_grab and os.path.exists(filtered_csv):
        try:
            filtered_df = pd.read_csv(filtered_csv, encoding="utf-8")
            logger.info(f"cache hit: {filtered_csv}", extra={"request_id": request_id})
        except Exception:
            logger.exception("cache read failed", extra={"request_id": request_id})
            filtered_df = None

    if filtered_df is None:
        grabber = None
        try:
            grabber = ChampionatGrabber()
            matches = grabber.grab(date_str, save_csv=False, request_id=request_id)
            grabber.close()

            logger.info(f"grabbed {len(matches)} matches", extra={"request_id": request_id})
            if not matches:
                return "Матчи не найдены"

            _write_csv(matches, matches_csv)

            matches_df     = pd.DataFrame(matches)
            tournaments_df = load_tournaments(TOURNAMENTS_PATH)
            filtered_df    = filter_matches_by_tournaments(matches_df, tournaments_df)
            filtered_df.to_csv(filtered_csv, index=False, encoding="utf-8")

        except Exception:
            logger.exception("pipeline error", extra={"request_id": request_id})
            if grabber:
                try:
                    grabber.close()
                except Exception:
                    pass
            return "Ошибка обработки данных"

    if filtered_df is None or filtered_df.empty:
        return "Матчи после фильтрации не найдены. Вероятно день зелёный или есть только киберсобытия"

    short_names      = load_short_names(TOURNAMENTS_PATH)
    tournaments_line = collect_tournament_names(filtered_df, short_names)

    try:
        output = format_output(filtered_df, date_str, tournaments_line, short_names)
    except Exception:
        logger.exception("format error", extra={"request_id": request_id})
        return "Ошибка формирования вывода"

    logger.info(f"pipeline done", extra={"request_id": request_id, "user_id": uid, "username": uname})
    return output