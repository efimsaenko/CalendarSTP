"""
MonthPipeline.py — логика месячного пайплайна.

Публичный API:
    run_month_pipeline(month_str, base_dir, force_grab=False) -> dict
    get_calendar_path(month_str, base_dir) -> str | None
    get_status_path(month_str, base_dir) -> str | None
    compare_day_colors(old, new) -> dict
    format_changes_message(changed, month_str) -> str

CLI:
    python MonthPipeline.py 05.2026
    python MonthPipeline.py 05.2026 --force
    python MonthPipeline.py 05.2026 --base-dir /path/to/project
"""

import os
import sys
import time
import logging
from datetime import datetime
from typing import Optional, Dict, Tuple, List

try:
    from logger import get_logger
    logger = get_logger("MonthPipeline")
except ImportError:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("MonthPipeline")

# Пауза между retry-попытками одного упавшего дня (секунды)
_DAY_RETRY_DELAY = 15
# Сколько раз повторять отдельный упавший день
_DAY_RETRIES = 2


# ---------------------------------------------------------------------------
# Утилиты путей
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Работа с daily_summary в xlsx
# ---------------------------------------------------------------------------

def _read_failed_days(matches_path: str) -> List[str]:
    """
    Читает лист daily_summary из matches xlsx.
    Возвращает список дат (YYYY-MM-DD) где matches_count == 0 или status == 'failed'.
    Дубликаты убираем — берём последнюю запись по каждой дате (самую свежую).
    """
    import pandas as pd
    if not os.path.exists(matches_path):
        return []
    try:
        df = pd.read_excel(
            matches_path, sheet_name="daily_summary",
            dtype=str, engine="openpyxl",
        )
        df.columns = [c.strip().lower() for c in df.columns]

        # Оставляем последнюю запись по каждой дате — она отражает актуальный статус
        df = df.drop_duplicates(subset=["date"], keep="last")

        mask = (
            (df["matches_count"].astype(str).str.strip() == "0") |
            (df["status"].str.strip() == "failed")
        )
        return df.loc[mask, "date"].str.strip().tolist()
    except Exception as e:
        logger.warning(f"Не удалось прочитать daily_summary: {e}")
        return []


def _retry_failed_days(
    scheduler,
    failed_days: List[str],
) -> Tuple[List[str], List[str]]:
    """
    Точечно переграбирует упавшие дни через grab_one_day.
    Возвращает (recovered, still_failed).
    """
    recovered: List[str] = []
    still_failed: List[str] = []

    for date_str in failed_days:
        success = False
        for attempt in range(1, _DAY_RETRIES + 1):
            logger.info(
                f"[pipeline] retry day {date_str} "
                f"attempt {attempt}/{_DAY_RETRIES}"
            )
            count = scheduler.grab_one_day(date_str, force_grab=True)
            if count > 0:
                logger.info(f"[pipeline] recovered {date_str}: {count} матчей")
                recovered.append(date_str)
                success = True
                break
            if attempt < _DAY_RETRIES:
                logger.warning(
                    f"[pipeline] {date_str} всё ещё 0, "
                    f"повтор через {_DAY_RETRY_DELAY}с..."
                )
                time.sleep(_DAY_RETRY_DELAY)

        if not success:
            logger.error(
                f"[pipeline] {date_str} не восстановлен "
                f"после {_DAY_RETRIES} попыток"
            )
            still_failed.append(date_str)

    return recovered, still_failed


# ---------------------------------------------------------------------------
# Основная функция
# ---------------------------------------------------------------------------

def run_month_pipeline(
    month_str: str,
    base_dir: str,
    force_grab: bool = False,
) -> dict:
    """
    Полный пайплайн за месяц:
      1. MonthGrabbScheduler  — парсим матчи по всем дням
      2. Точечный retry       — дограбливаем только упавшие дни (0 матчей / failed)
      3. MonthMatchFilter     — фильтруем, считаем цвета
      4. MonthCalendarExcel   — генерируем Excel

    Возвращает:
        {"status": "ok",    "calendar_path": str, "month_str": str,
         "changed": dict,   "recovered": list,    "still_failed": list}
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
        matches_path = os.path.join(
            base_dir, "data", str(year), f"{month:02d}",
            f"matches_{year}_{month:02d}.xlsx"
        )

        scheduler = MonthGrabbScheduler(
            data_root=os.path.join(base_dir, "data")
        )

        # 1. Первичный граббинг
        if force_grab or not os.path.exists(matches_path):
            logger.info(f"[pipeline] grabbing {month_str}")
            scheduler.run_month(year, month, force_grab=force_grab)
        else:
            logger.info("[pipeline] matches exist, skip grab")

        # 2. Точечный retry — только реально упавшие дни, не весь месяц
        failed_days = _read_failed_days(matches_path)
        if failed_days:
            logger.warning(
                f"[pipeline] упавших дней: {len(failed_days)} → {failed_days}"
            )
            recovered, still_failed = _retry_failed_days(scheduler, failed_days)
        else:
            logger.info("[pipeline] упавших дней нет")
            recovered, still_failed = [], []

        if still_failed:
            logger.error(
                f"[pipeline] дни без данных после retry: {still_failed} — "
                f"продолжаем с имеющимися данными"
            )

        # 3. Старые цвета для diff
        old_colors: Dict[str, str] = {}
        if force_grab:
            old_colors = load_old_colors(get_status_path(month_str, base_dir))

        # 4. Фильтрация
        logger.info(f"[pipeline] filtering {month_str}")
        run_filter(month_str, base_dir)

        # 5. Diff цветов
        changed: Dict[str, Tuple[str, str]] = {}
        if force_grab and old_colors:
            new_colors = load_old_colors(get_status_path(month_str, base_dir))
            changed    = compare_day_colors(old_colors, new_colors)
            if changed:
                logger.info(f"[pipeline] color changes: {changed}")

        # 6. Excel-календарь
        logger.info(f"[pipeline] generating calendar {month_str}")
        calendar_path = create_month_calendar(month_str, base_dir)

        logger.info(f"[pipeline] done → {calendar_path}")
        return {
            "status":        "ok",
            "calendar_path": calendar_path,
            "month_str":     month_str,
            "changed":       changed,
            "recovered":     recovered,
            "still_failed":  still_failed,
        }

    except Exception as e:
        logger.exception(f"[pipeline] error: {e}")
        return {"status": "error", "error": str(e), "month_str": month_str}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args():
    import argparse
    p = argparse.ArgumentParser(
        description="Месячный пайплайн: граббинг → фильтрация → календарь",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Примеры:\n"
            "  python MonthPipeline.py 05.2026\n"
            "  python MonthPipeline.py 05.2026 --force\n"
            "  python MonthPipeline.py 05.2026 --base-dir /srv/bot\n"
        ),
    )
    p.add_argument(
        "month",
        metavar="MM.YYYY",
        help="Месяц для обработки, например 05.2026",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Переграбить даже если файл матчей уже существует",
    )
    p.add_argument(
        "--base-dir",
        default=None,
        metavar="PATH",
        help="Корень проекта (по умолчанию — директория этого скрипта)",
    )
    return p.parse_args()


if __name__ == "__main__":
    args     = _parse_args()
    base_dir = args.base_dir or os.path.dirname(os.path.abspath(__file__))

    result = run_month_pipeline(args.month, base_dir, force_grab=args.force)

    if result["status"] == "ok":
        print(f"\n✅ Готово → {result['calendar_path']}")
        if result.get("recovered"):
            print(f"   Восстановлено дней:       {result['recovered']}")
        if result.get("still_failed"):
            print(f"   ⚠️  Не восстановлено дней: {result['still_failed']}")
        sys.exit(0)
    else:
        print(f"\n❌ Ошибка: {result['error']}", file=sys.stderr)
        sys.exit(1)
