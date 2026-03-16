"""
MonthPipeline.py — логика месячного пайплайна.

Публичный API:
    run_month_pipeline(month_str, base_dir, force_grab=False) -> dict
    get_calendar_path(month_str, base_dir) -> str | None
    get_status_path(month_str, base_dir) -> str | None
    compare_day_colors(old, new) -> dict
    format_changes_message(changed, month_str) -> str
"""

import os
import logging
from datetime import datetime
from typing import Optional, Dict, Tuple

try:
    from logger import get_logger
    logger = get_logger("MonthPipeline")
except ImportError:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("MonthPipeline")


def get_calendar_path(month_str: str, base_dir: str) -> Optional[str]:
    """Путь к calendar.xlsx если существует, иначе None."""
    try:
        dt = datetime.strptime(month_str, "%m.%Y")
    except ValueError:
        return None
    path = os.path.join(
        base_dir, "data", str(dt.year), f"{dt.month:02d}",
        f"{dt.month:02d}.{dt.year}_calendar.xlsx"
    )
    return path if os.path.exists(path) else None


def get_status_path(month_str: str, base_dir: str) -> Optional[str]:
    """Путь к status.csv если существует, иначе None."""
    try:
        dt = datetime.strptime(month_str, "%m.%Y")
    except ValueError:
        return None
    path = os.path.join(
        base_dir, "data", str(dt.year), f"{dt.month:02d}",
        f"{dt.month:02d}.{dt.year}_status.csv"
    )
    return path if os.path.exists(path) else None


def load_old_colors(status_path: str) -> Dict[str, str]:
    """Читает status.csv → {DD.MM.YYYY: color}."""
    import pandas as pd
    if not status_path or not os.path.exists(status_path):
        return {}
    try:
        df = pd.read_csv(status_path, sep=";", dtype=str)
        df.columns = [c.strip().lower() for c in df.columns]
        return {
            row["date"].strip(): row["color"].strip().lower()
            for _, row in df.iterrows()
            if "date" in row and "color" in row
        }
    except Exception as e:
        logger.warning(f"Не удалось прочитать статусы: {e}")
        return {}


def compare_day_colors(
    old_colors: Dict[str, str],
    new_colors: Dict[str, str],
) -> Dict[str, Tuple[str, str]]:
    """Возвращает {DD.MM.YYYY: (old, new)} только для изменившихся дней."""
    return {
        day: (old_colors.get(day, "green"), new_colors.get(day, "green"))
        for day in set(old_colors) | set(new_colors)
        if old_colors.get(day, "green") != new_colors.get(day, "green")
    }


def format_changes_message(changed: Dict[str, Tuple[str, str]], month_str: str) -> str:
    """Форматирует сообщение об изменениях для Telegram."""
    ICON = {"red": "🔴", "yellow": "🟡", "green": "🟢"}
    if not changed:
        return f"📅 Обновление {month_str}: изменений в расписании нет."
    lines = [f"📅 <b>Обновление {month_str}</b> — изменения в расписании:\n"]
    for day in sorted(changed, key=lambda d: datetime.strptime(d, "%d.%m.%Y")):
        old, new = changed[day]
        lines.append(f"  {day}: {ICON.get(old,'⚪')} → {ICON.get(new,'⚪')}")
    return "\n".join(lines)


def run_month_pipeline(
    month_str: str,
    base_dir: str,
    force_grab: bool = False,
) -> dict:
    """
    Полный пайплайн за месяц:
      1. MonthGrabbScheduler  — парсим матчи
      2. MonthMatchFilter     — фильтруем, считаем цвета
      3. MonthCalendarExcel   — генерируем Excel

    Возвращает:
        {"status": "ok",    "calendar_path": str, "month_str": str, "changed": dict}
        {"status": "error", "error": str,         "month_str": str}
    """
    from MonthGrabbScheduler import MonthGrabbScheduler
    from MonthMatchFilter    import run_filter
    from MonthCalendarExcel  import create_month_calendar

    try:
        dt = datetime.strptime(month_str, "%m.%Y")
        year, month = dt.year, dt.month
    except ValueError as e:
        return {"status": "error", "error": str(e), "month_str": month_str}

    logger.info(f"[pipeline] start {month_str} force={force_grab}")

    try:
        # 1. Парсинг
        matches_path = os.path.join(
            base_dir, "data", str(year), f"{month:02d}",
            f"matches_{year}_{month:02d}.xlsx"
        )
        if force_grab or not os.path.exists(matches_path):
            logger.info(f"[pipeline] grabbing {month_str}")
            MonthGrabbScheduler(
                data_root=os.path.join(base_dir, "data")
            ).run_month(year, month, force_grab=force_grab)
        else:
            logger.info("[pipeline] matches exist, skip grab")

        # 2. Старые цвета для diff
        old_colors: Dict[str, str] = {}
        if force_grab:
            old_colors = load_old_colors(get_status_path(month_str, base_dir))

        # 3. Фильтрация
        logger.info(f"[pipeline] filtering {month_str}")
        run_filter(month_str, base_dir)

        # 4. Diff цветов
        changed: Dict[str, Tuple[str, str]] = {}
        if force_grab and old_colors:
            new_colors = load_old_colors(get_status_path(month_str, base_dir))
            changed    = compare_day_colors(old_colors, new_colors)
            if changed:
                logger.info(f"[pipeline] color changes: {changed}")

        # 5. Excel
        logger.info(f"[pipeline] generating calendar {month_str}")
        calendar_path = create_month_calendar(month_str, base_dir)

        logger.info(f"[pipeline] done → {calendar_path}")
        return {
            "status":        "ok",
            "calendar_path": calendar_path,
            "month_str":     month_str,
            "changed":       changed,
        }

    except Exception as e:
        logger.exception(f"[pipeline] error: {e}")
        return {"status": "error", "error": str(e), "month_str": month_str}