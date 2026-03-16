import os
import re
import logging
from typing import Dict, Tuple, Optional
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# -----------------------------
# Загрузка сокращений турниров
# -----------------------------
def load_short_names(path: str) -> Dict[str, str]:
    """
    Читает tournaments.csv и возвращает словарь {full: short}.
    Сигнатура не меняется — возвращает только {full: short}.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    df = pd.read_csv(path, sep=None, engine="python")
    cols = list(df.columns)

    if len(cols) >= 2:
        df = df.rename(columns={
            cols[0]: "full",
            cols[1]: "short",
            **({cols[2]: "color"} if len(cols) > 2 else {})
        })
    else:
        raise ValueError("tournaments.csv должен иметь минимум две колонки: full и short")

    if "full" not in df.columns or "short" not in df.columns:
        raise ValueError("tournaments.csv должен содержать колонки 'full' и 'short'")

    df["full"] = df["full"].astype(str).fillna("").str.strip()
    df["short"] = df["short"].astype(str).fillna("").str.strip()

    result = dict(zip(df["full"], df["short"]))
    logger.debug(f"Загружено {len(result)} турниров из {path}")
    return result


def _load_full_tournaments(path: str) -> pd.DataFrame:
    """
    Внутренняя: загружает tournaments.csv со всеми колонками (full, short, color).
    Нужна для определения цвета турниров при подчёркивании красных матчей.
    """
    if not os.path.exists(path):
        logger.warning(f"tournaments.csv не найден: {path}")
        return pd.DataFrame(columns=["full", "short", "color"])

    df = pd.read_csv(path, sep=None, engine="python")
    cols = list(df.columns)

    rename = {cols[0]: "full", cols[1]: "short"}
    if len(cols) > 2:
        rename[cols[2]] = "color"
    df = df.rename(columns=rename)

    df["full"] = df["full"].astype(str).fillna("").str.strip()
    df["short"] = df["short"].astype(str).fillna("").str.strip()
    if "color" in df.columns:
        df["color"] = df["color"].astype(str).fillna("").str.strip()
    else:
        df["color"] = ""

    logger.debug(f"Загружена таблица турниров: {len(df)} строк")
    return df


# -----------------------------
# Нормализация строк
# -----------------------------
def normalize_name(name: str) -> str:
    if not isinstance(name, str):
        return ""
    s = name.lower().replace("\xa0", " ")
    s = re.sub(r"[^a-zа-я0-9\s]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ---------------------------------
# Получение короткого названия
# ---------------------------------
def get_short_tournament_name(full_name: str, short_names_dict: Dict[str, str]) -> str:
    """
    Ищет подходящее короткое имя по полному названию.
    Fallback — первые 3 слова исходного названия.
    """
    if not isinstance(full_name, str):
        return ""

    normalized_full = normalize_name(full_name)
    for k, short in short_names_dict.items():
        if k and normalize_name(k) in normalized_full:
            return short

    parts = re.sub(r"[^A-Za-zА-Яа-я0-9\s]", " ", full_name).split()
    if not parts:
        return full_name.strip() or "Турнир"
    return " ".join(parts[:3]).strip()


# ---------------------------------
# Цвет дня из status-файла
# ---------------------------------
def _get_day_color(date_str: str, data_root: str) -> Tuple[str, bool]:
    """
    Читает файл вида:
        <data_root>/<YYYY>/<MM>/<MM.YYYY>status

    Формат файла (разделитель ;):
        date;color
        01.03.2026;yellow
        05.03.2026;red

    Возвращает: (иконка, is_red_day).
    Если файл не найден или дата отсутствует — возвращает ('🌕', False).
    """
    icon_map = {
        "red":    ("🔴", True),
        "yellow": ("🟡", False),
        "green":  ("🟢", False),
    }
    default = ("🌕", False)

    try:
        dt = pd.to_datetime(date_str)
        year  = dt.strftime("%Y")
        month = dt.strftime("%m")

        # путь: data_root/YYYY/MM/MM.YYYYstatus
        status_filename = f"{month}.{year}_status.csv"
        status_path = os.path.join(data_root, year, month, status_filename)

        logger.debug(f"Ищем status-файл: {status_path}")

        if not os.path.exists(status_path):
            logger.warning(f"Status-файл не найден: {status_path}")
            return default

        df = pd.read_csv(status_path, sep=";", encoding="utf-8", dtype=str)
        df.columns = [c.strip().lower() for c in df.columns]

        if "date" not in df.columns or "color" not in df.columns:
            logger.warning(f"Status-файл не содержит колонок date/color: {status_path}")
            return default

        df["date"] = pd.to_datetime(df["date"].str.strip(), dayfirst=True, errors="coerce")
        df["color"] = df["color"].str.strip().str.lower()

        target = pd.to_datetime(date_str)
        row = df.loc[df["date"] == target]

        if row.empty:
            logger.warning(f"Дата {date_str} не найдена в {status_path}")
            return default

        color = row.iloc[0]["color"]
        result = icon_map.get(color, default)
        logger.info(f"Цвет дня для {date_str}: {color} → {result[0]}")
        return result

    except Exception as e:
        logger.exception(f"Ошибка чтения status-файла для {date_str}: {e}")
        return default


# ---------------------------------
# Красные турниры для подчёркивания
# ---------------------------------
def _get_red_tournament_shorts(tournaments_df: pd.DataFrame) -> set:
    """
    Возвращает множество коротких имён турниров со статусом 'Красный' из tournaments.csv.
    """
    if "color" not in tournaments_df.columns:
        return set()

    red = tournaments_df[
        tournaments_df["color"].str.strip().str.lower() == "красный"
    ]["short"].astype(str).str.strip().tolist()

    logger.debug(f"Красные турниры из tournaments.csv: {red}")
    return set(red)


# ---------------------------------
# Сбор строки турниров
# ---------------------------------
def collect_tournament_names(matches_df: pd.DataFrame, short_names_dict: Dict[str, str]) -> str:
    """
    Возвращает строку с перечислением коротких названий / чемпионатов.
    Сигнатура не меняется.
    """
    if isinstance(matches_df, str):
        if not os.path.exists(matches_df):
            raise FileNotFoundError(f"Файл не найден: {matches_df}")
        matches_df = pd.read_csv(matches_df)

    if not isinstance(matches_df, pd.DataFrame):
        raise TypeError("collect_tournament_names ожидал DataFrame или путь к CSV")

    if "tournament" not in matches_df.columns:
        return ""

    abbreviations = []
    championships = []
    abbrev_set = {v for v in short_names_dict.values() if not str(v).startswith("Чемпионат")}

    for full_name in matches_df["tournament"].fillna("").unique():
        if not isinstance(full_name, str) or not full_name.strip():
            continue

        matched = False
        norm_full = normalize_name(full_name)

        for k, short in short_names_dict.items():
            if k and normalize_name(k) in norm_full:
                if short in abbrev_set:
                    if short not in abbreviations:
                        abbreviations.append(short)
                else:
                    parts = short.split()
                    country = " ".join(parts[1:]) if len(parts) > 1 else short
                    if country not in championships:
                        championships.append(country)
                matched = True
                break

        if not matched:
            logger.debug(f"Не найдено соответствие для турнира: {full_name}")

    result_parts = abbreviations.copy()
    if championships:
        result_parts.append(f"Чемпионаты {', '.join(championships)}")

    line = ", ".join(result_parts)
    logger.debug(f"Строка турниров: {line}")
    return line


# ---------------------------------
# Формирование финального текста
# ---------------------------------
DASH_RE = re.compile(r"^[\s\-\u2010\u2011\u2012\u2013\u2014\u2015]+$")


def format_output(
    matches_df: pd.DataFrame,
    date_str: str,
    tournaments_line: str,
    short_names_dict: Dict[str, str],
    load_icon: str = None
) -> str:
    """
    Форматирует вывод для Telegram (Markdown).

    Логика иконки дня:
    - Если load_icon передан явно — используется он (красные матчи не подчёркиваются)
    - Иначе читается <data_root>/YYYY/MM/MM.YYYYstatus по date_str
      data_root = директория скрипта / data

    Логика подчёркивания:
    - Если день красный — матчи турниров помеченных 'Красный' в tournaments.csv
      оборачиваются в __текст__ (underline Markdown)

    Сигнатура не меняется.
    """
    logger.info(f"Форматирование для даты: {date_str}")

    # --- Нормализация входа ---
    if isinstance(matches_df, str):
        if os.path.exists(matches_df):
            matches_df = pd.read_csv(matches_df)
        else:
            raise FileNotFoundError(f"matches_df path not found: {matches_df}")

    if not isinstance(matches_df, pd.DataFrame):
        raise TypeError("matches_df должен быть pandas.DataFrame")

    base_dir = os.path.dirname(os.path.abspath(__file__))
    tournaments_path = os.path.join(base_dir, "tournaments.csv")
    data_root = os.path.join(base_dir, "data")  # ← data_root = base_dir/data

    if load_icon is not None:
        day_icon = load_icon
        is_red_day = False
    else:
        day_icon, is_red_day = _get_day_color(date_str, data_root)

    # --- Красные турниры для подчёркивания ---
    if is_red_day:
        tournaments_df = _load_full_tournaments(tournaments_path)
        red_shorts = _get_red_tournament_shorts(tournaments_df)
    else:
        red_shorts = set()

    logger.info(f"Иконка: {day_icon} | Красный день: {is_red_day} | Красные турниры: {red_shorts}")

    # --- Форматирование даты ---
    try:
        formatted_date = pd.to_datetime(date_str).strftime("%d.%m.%Y")
    except Exception:
        formatted_date = date_str

    # --- Шапка ---
    header = f"{day_icon} {formatted_date}"
    if tournaments_line:
        header += f" {tournaments_line}"
    header_bold = f"<b>{header.strip()}</b>\n\n"


    # --- Гарантируем колонки ---
    if "time" not in matches_df.columns:
        matches_df = matches_df.copy()
        matches_df["time"] = ""
    if "participants" not in matches_df.columns:
        matches_df = matches_df.copy()
        matches_df["participants"] = ""

    # --- Сортировка по времени ---
    try:
        sorted_df = matches_df.copy()
        sorted_df["_time_sort"] = sorted_df["time"].fillna("").astype(str)
        sorted_df = sorted_df.sort_values("_time_sort").drop(columns=["_time_sort"])
    except Exception:
        logger.warning("Не удалось отсортировать по времени, используем исходный порядок")
        sorted_df = matches_df

    # --- Строки матчей ---
    lines = []
    for _, row in sorted_df.iterrows():
        time_str = str(row.get("time", "")).strip()
        part_raw = row.get("participants", "")

        if pd.isna(part_raw):
            participants = ""
        else:
            participants = str(part_raw).strip()

        is_dash_like = (
            not participants
            or participants.lower() in ("nan", "none")
            or bool(DASH_RE.match(participants))
        )

        if is_dash_like:
            full_t = str(row.get("tournament", "") or "")
            short_name = get_short_tournament_name(full_t, short_names_dict)
            participants = f"{short_name}. Команды еще не назначены"

        line = f"{time_str} {participants}".strip()

        # Подчёркиваем если день красный и турнир красный
        if is_red_day and red_shorts:
            full_t = str(row.get("tournament", "") or "")
            match_short = get_short_tournament_name(full_t, short_names_dict)
            if match_short in red_shorts:
                line = f"<u>{line}</u>"
                logger.debug(f"Подчёркнут матч: {line}")

        lines.append(line)

    result = header_bold + "\n".join(lines)
    logger.info(f"Готово: {len(lines)} матчей")
    return result


# ---------------------------------
# Быстрый тест при запуске как скрипт
# ---------------------------------
if __name__ == "__main__":
    base_dir  = os.path.dirname(os.path.abspath(__file__))
    test_date = "2026-03-12"

    dt    = pd.to_datetime(test_date)
    year  = dt.strftime("%Y")
    month = dt.strftime("%m")

    data_root    = os.path.join(base_dir, "data")
    matches_path = os.path.join(data_root, year, month, f"filtered_{test_date}.csv")

    try:
        short_names = load_short_names(os.path.join(base_dir, "tournaments.csv"))
    except Exception as e:
        logger.error(f"Не удалось загрузить tournaments.csv: {e}")
        short_names = {}

    if os.path.exists(matches_path):
        try:
            df = pd.read_csv(matches_path)
            tournaments_line = collect_tournament_names(df, short_names)
            out = format_output(df, test_date, tournaments_line, short_names)
            print(out)
        except Exception as e:
            logger.exception(f"Ошибка при тестовом запуске: {e}")
    else:
        logger.info(f"Тестовый файл не найден: {matches_path}")