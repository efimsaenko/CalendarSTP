# MonthMatchFilter.py
"""
Анализирует матчи за месяц, фильтрует по tournaments.csv,
записывает статусы в status.csv и сохраняет отфильтрованный список.

Входные данные:
    month_str — строка "03.2026"

Структура файлов:
    base_dir/data/YYYY/MM/matches_YYYY_MM.xlsx     — исходные матчи
    base_dir/tournaments.csv                        — фильтр турниров (full, short, color)
    base_dir/data/YYYY/MM/MM.YYYY_status.csv        — статусы дней (date;color)
    base_dir/data/YYYY/MM/MM.YYYY_filtered.xlsx     — отфильтрованный вывод

Колонки matches:
    tournament | date | time | participants | request_id

Публичный API:
    run_filter(month_str, base_dir)                          — основная функция
    add_tournament(name, short, color, base_dir, year, month) — добавить турнир в фильтр
    get_filtered_path(year, month, base_dir)                 — путь к filtered файлу
"""

import os
import csv
import re
import sys
import logging
from datetime import datetime, date
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------
try:
    from logger import get_logger
    logger = get_logger("MonthMatchFilter")
except ImportError:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    logger = logging.getLogger("MonthMatchFilter")

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

# Эскалация: если в день >= N матчей красных турниров — день становится red
RED_ESCALATION_THRESHOLD = 3
RED_MIN_THRESHOLD = 1

# Порог суммарных матчей турниров с escalation=1 для эскалации дня green → yellow
GREEN_ESCALATION_THRESHOLD = 10

# Минимальная доля совпавших слов для «потенциально важного» турнира
POTENTIAL_MATCH_RATIO = 0.45

# Минимальное кол-во матчей в «потенциально важном» турнире
POTENTIAL_MIN_MATCHES = 3

# Таблица нормализации цветов — принимаем все возможные варианты написания
# включая кириллицу с заглавной (как в реальном файле: "Желтый", "Красный")
COLOR_NORMALIZE: Dict[str, str] = {
    # Русские варианты
    "красный":  "red",
    "красной":  "red",
    "жёлтый":   "yellow",
    "желтый":   "yellow",
    "жёлтой":   "yellow",
    "желтой":   "yellow",
    "зелёный":  "green",
    "зеленый":  "green",
    "зелёной":  "green",
    "зеленой":  "green",
    # Английские варианты
    "red":      "red",
    "yellow":   "yellow",
    "green":    "green",
}


def _normalize_color(raw: str) -> str:
    """
    Нормализует цвет из tournaments.csv в одно из: red / yellow / green / "".
    Принимает любой регистр и любой язык из таблицы COLOR_NORMALIZE.
    Пример: "Желтый" -> "yellow", "КРАСНЫЙ" -> "red"
    """
    key = raw.strip().lower()
    return COLOR_NORMALIZE.get(key, "")


# ---------------------------------------------------------------------------
# Пути
# ---------------------------------------------------------------------------

def _base(base_dir: Optional[str] = None) -> str:
    return base_dir or os.path.dirname(os.path.abspath(__file__))


def get_filtered_path(year: int, month: int, base_dir: Optional[str] = None) -> str:
    return os.path.join(_base(base_dir), "data", str(year), f"{month:02d}",
                        f"{month:02d}.{year}_filtered.xlsx")


def _matches_path(year: int, month: int, base_dir: Optional[str] = None) -> str:
    return os.path.join(_base(base_dir), "data", str(year), f"{month:02d}",
                        f"matches_{year}_{month:02d}.xlsx")


def _status_path(year: int, month: int, base_dir: Optional[str] = None) -> str:
    """Путь: base_dir/data/YYYY/MM/MM.YYYY_status.csv"""
    return os.path.join(_base(base_dir), "data", str(year), f"{month:02d}",
                        f"{month:02d}.{year}_status.csv")


def _tournaments_path(base_dir: Optional[str] = None) -> str:
    return os.path.join(_base(base_dir), "tournaments.csv")


# ---------------------------------------------------------------------------
# Загрузка данных
# ---------------------------------------------------------------------------

def _load_matches(year: int, month: int, base_dir: Optional[str] = None) -> pd.DataFrame:
    """
    Загружает matches_YYYY_MM.xlsx.
    Оптимизировано для больших файлов (50k+ строк) — читаем через pandas/openpyxl,
    dtype=str чтобы не терять нули во времени и request_id.
    """
    path = _matches_path(year, month, base_dir)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Файл матчей не найден: {path}")

    logger.info(f"Загрузка матчей: {path}")
    df = pd.read_excel(path, dtype=str, engine="openpyxl")
    df.columns = [c.strip().lower() for c in df.columns]

    required = {"tournament", "date", "time", "participants"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"В файле матчей отсутствуют колонки: {missing}")

    df = df.fillna("")
    df["tournament"] = df["tournament"].str.strip()

    # Нормализуем дату — приводим любой формат к YYYY-MM-DD
    # Excel может хранить дату как datetime ("2026-03-14 00:00:00") или строку
    def _norm_date(val: str) -> str:
        val = str(val).strip()
        # уже правильный формат
        if len(val) >= 10 and val[4] == "-" and val[7] == "-":
            return val[:10]
        # пробуем распарсить другие форматы
        for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d", "%m/%d/%Y"):
            try:
                from datetime import datetime as _dt
                return _dt.strptime(val[:10], fmt).strftime("%Y-%m-%d")
            except Exception:
                continue
        return val  # вернём как есть если не распарсили

    df["date"] = df["date"].astype(str).apply(_norm_date)

    logger.info(f"Загружено {len(df):,} строк, "
                f"{df['tournament'].nunique()} уникальных турниров")

    # Диагностика: выводим уникальные форматы дат
    sample_dates = df["date"].unique()[:3].tolist()
    logger.debug(f"Пример дат после нормализации: {sample_dates}")

    return df


def _load_tournaments(base_dir: Optional[str] = None) -> pd.DataFrame:
    """
    Загружает tournaments.csv → DataFrame с колонками: full, short, color_norm.

    Формат файла (разделитель ;):
        tournament;short;importants
        Англия — Премьер-лига.;АПЛ;Зеленый

    Первый столбец (tournament/full) — ключ фильтра и поиска совпадений.
    Третий столбец (importants/color) — нагрузка: Красный/Желтый/Зеленый.
    """
    path = _tournaments_path(base_dir)
    if not os.path.exists(path):
        raise FileNotFoundError(f"tournaments.csv не найден: {path}")

    # Явный разделитель ; — файл всегда в таком формате
    df = pd.read_csv(path, sep=";", dtype=str)

    # Нормализуем названия колонок: убираем пробелы, приводим к нижнему регистру
    df.columns = [c.strip().lower() for c in df.columns]

    # Поддерживаем оба варианта названия первой колонки: tournament / full
    if "tournament" in df.columns:
        df = df.rename(columns={"tournament": "full"})

    # Поддерживаем оба варианта колонки цвета: importants / color
    if "importants" in df.columns:
        df = df.rename(columns={"importants": "color"})

    # Гарантируем наличие всех нужных колонок
    if "full" not in df.columns:
        raise ValueError("tournaments.csv должен содержать колонку 'tournament' или 'full'")
    if "short" not in df.columns:
        df["short"] = df["full"]
    if "color" not in df.columns:
        df["color"] = ""

    # Чистим пробелы во всех значимых колонках
    df["full"]  = df["full"].astype(str).str.strip()
    df["short"] = df["short"].astype(str).str.strip()
    df["color"] = df["color"].astype(str).str.strip()

    # Колонка escalation: 1 = участвует в подсчёте green-эскалации, 0 = нет
    # Если колонки нет в файле — по умолчанию 0 для всех
    if "escalation" in df.columns:
        df["escalation"] = pd.to_numeric(df["escalation"].str.strip(), errors="coerce").fillna(0).astype(int)
    else:
        df["escalation"] = 0

    # Нормализуем цвет прямо при загрузке
    df["color_norm"] = df["color"].apply(_normalize_color)

    # Лог предупреждений о нераспознанных цветах
    unknown = df[(df["color_norm"] == "") & df["color"].ne("")]["color"].unique().tolist()
    if unknown:
        logger.warning(f"Нераспознанные значения цвета в tournaments.csv: {unknown}")

    logger.info(f"Загружено {len(df)} турниров | "
                f"red={( df['color_norm']=='red').sum()} "
                f"yellow={(df['color_norm']=='yellow').sum()} "
                f"green={ (df['color_norm']=='green').sum()}")
    return df


# ---------------------------------------------------------------------------
# Нормализация и сравнение названий
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    s = text.lower().replace("\xa0", " ")
    # ё → е чтобы не разрезало слово при удалении спецсимволов
    s = s.replace("ё", "е").replace("ъ", "ь")
    s = re.sub(r"[^a-zа-я0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _words(text: str) -> Set[str]:
    return set(_normalize(text).split())


import re as _re

# Слова-квалификаторы: если они есть в названии матча, но НЕ в эталоне,
# значит это другой турнир (женский, молодёжный и т.д.) — не совпадение.
_QUALIFIER_WORDS = frozenset([
    "женская", "женский", "женщины", "женщин",
    "women", "woman", "female",
    "u21", "u19", "u18", "u17", "u16", "u15", "u23",
    "молодежная", "молодежный", "молодежные",
    "юношеская", "юношеский", "юношеские",
    "youth", "junior", "reserve", "резерв",
    "академия", "academy",
])

# Паттерны-квалификаторы в скобках: (ж), (w), (f), (жен) и т.п.
# Ищем в оригинальном (не нормализованном) названии, до нормализации
_QUALIFIER_BRACKET_RE = _re.compile(
    r"\(\s*(?:ж|жен|w|f|women|female|youth|u\d{2})\s*\)",
    _re.IGNORECASE
)


def _has_bracket_qualifier(text: str) -> bool:
    """True если в тексте есть маркер женского/молодёжного турнира в скобках."""
    return bool(_QUALIFIER_BRACKET_RE.search(text))


def _is_match(tournament_name: str, reference_full: str) -> bool:
    """
    Совпадение турнира с эталоном из tournaments.csv.

    Стратегия:
    1. Нормализованный эталон содержится в нормализованном названии матча
       Пример: 'англия премьер лига' in 'англия премьер лига 30 й тур' → True
    2. Нормализованное название начинается с нормализованного эталона

    Защита от ложных срабатываний (два уровня):
    A) Скобочные квалификаторы: если название матча содержит (ж), (w), (f) и т.п.,
       а эталон — нет, это другой турнир.
       Пример: 'Лига Чемпионов (ж)' НЕ совпадает с 'Лига чемпионов.'
    B) Словесные квалификаторы: слова женская/u21/молодежная и т.п. в названии
       матча, которых нет в эталоне → отклоняем.
    """
    # ── Уровень A: скобочные квалификаторы (до нормализации) ────────────
    t_has_bracket   = _has_bracket_qualifier(tournament_name)
    ref_has_bracket = _has_bracket_qualifier(reference_full)
    if t_has_bracket and not ref_has_bracket:
        return False

    t_norm   = _normalize(tournament_name)
    ref_norm = _normalize(reference_full)
    if not ref_norm:
        return False

    # ── Базовое совпадение ───────────────────────────────────────────────
    matched = ref_norm in t_norm or t_norm.startswith(ref_norm)
    if not matched:
        return False

    # ── Уровень B: словесные квалификаторы ──────────────────────────────
    t_words   = set(t_norm.split())
    ref_words = set(ref_norm.split())
    extra     = t_words - ref_words  # слова есть в матче, но не в эталоне

    if extra & _QUALIFIER_WORDS:
        return False

    return True


def _potential_score(tournament_name: str, reference_full: str) -> float:
    """Доля слов эталона найденных в названии турнира."""
    ref_words = _words(reference_full)
    if not ref_words:
        return 0.0
    return len(ref_words & _words(tournament_name)) / len(ref_words)


# ---------------------------------------------------------------------------
# Фильтрация
# ---------------------------------------------------------------------------

def _filter_matches(
    df: pd.DataFrame,
    tournaments_df: pd.DataFrame
) -> Tuple[pd.DataFrame, List[str], List[str], List[Tuple[str, float, int]]]:
    """
    Фильтрует df по tournaments_df.
    Оптимизация: сначала классифицируем уникальные турниры (~десятки),
    потом одним isin() фильтруем весь DataFrame.

    Возвращает:
        filtered_df    — прошедшие фильтр строки
        matched_names  — уникальные турниры прошедшие фильтр
        skipped_names  — уникальные скипнутые турниры
        potential_list — [(name, score, match_count)] потенциально важные
    """
    references    = tournaments_df["full"].tolist()
    unique_all    = df["tournament"].unique().tolist()
    counts        = df["tournament"].value_counts().to_dict()

    logger.info(f"Классификация {len(unique_all)} уникальных турниров...")

    matched_set: Set[str] = set()
    skipped_set: Set[str] = set()
    potential_scores: Dict[str, float] = {}

    for t_name in unique_all:
        if not t_name:
            continue
        found = any(_is_match(t_name, ref) for ref in references)
        if found:
            matched_set.add(t_name)
        else:
            skipped_set.add(t_name)
            best = max((_potential_score(t_name, ref) for ref in references), default=0.0)
            potential_scores[t_name] = best

    filtered_df = df[df["tournament"].isin(matched_set)].copy()

    potential_list = [
        (name, score, counts.get(name, 0))
        for name, score in potential_scores.items()
        if score >= POTENTIAL_MATCH_RATIO and counts.get(name, 0) >= POTENTIAL_MIN_MATCHES
    ]
    potential_list.sort(key=lambda x: (-x[1], -x[2]))

    return filtered_df, sorted(matched_set), sorted(skipped_set), potential_list


# ---------------------------------------------------------------------------
# Расчёт нагрузки по дням
# ---------------------------------------------------------------------------

def _compute_day_colors(
    filtered_df: pd.DataFrame,
    tournaments_df: pd.DataFrame,
    year: int,
    month: int
) -> Dict[str, str]:
    """
    Вычисляет цвет дня по матчам из filtered_df.

    Логика приоритетов:
      red    = 3  (Красный турнир)
      yellow = 2  (Желтый турнир)
      green  = 1  (Зеленый турнир)

    Эскалация: >= RED_ESCALATION_THRESHOLD матчей red-турниров в день → red

    Возвращает {DD.MM.YYYY: "red"/"yellow"/"green"}
    """
    # Карта: full_name -> color_norm (через нормализованный цвет)
    full_to_color: Dict[str, str] = {}
    for _, row in tournaments_df.iterrows():
        full_to_color[row["full"]] = row.get("color_norm", "")

    # Строим карту tournament_name -> color_norm через _is_match
    ref_full_list = tournaments_df["full"].tolist()

    def get_color(t_name: str) -> str:
        for ref in ref_full_list:
            if _is_match(t_name, ref):
                return full_to_color.get(ref, "")
        return ""

    import calendar as _calendar

    # Строим карту: full → escalation
    full_to_escalation: Dict[str, int] = {}
    for _, row in tournaments_df.iterrows():
        full_to_escalation[row["full"]] = int(row.get("escalation", 0))

    def get_escalation(t_name: str) -> int:
        for ref in ref_full_list:
            if _is_match(t_name, ref):
                return full_to_escalation.get(ref, 0)
        return 0

    df = filtered_df.copy()
    df["_color_norm"]  = df["tournament"].apply(get_color)
    df["_escalation"]  = df["tournament"].apply(get_escalation)

    # Диагностика: сводка по эскалации
    esc_summary = df.groupby("date")["_escalation"].sum().to_dict()
    logger.info(f"Суммы escalation по дням: {esc_summary}")

    # Дни с матчами
    days_with_matches: Dict[str, str] = {}

    for day_str, group in df.groupby("date"):
        try:
            d = datetime.strptime(str(day_str)[:10], "%Y-%m-%d").date()
        except Exception:
            continue
        if d.year != year or d.month != month:
            continue

        red_count       = int((group["_color_norm"] == "red").sum())
        yellow_count    = int((group["_color_norm"] == "yellow").sum())
        escalation_count = int((group["_escalation"] == 1).sum())

        # Правила покраски дня:
        # 1. red >= RED_ESCALATION_THRESHOLD (3)  → red
        # 2. red > 0 и red+yellow >= 3            → red
        # 3. red >= RED_MIN_THRESHOLD (1)          → red  (любой красный турнир)
        # 4. yellow >= 5                           → yellow
        # 5. escalation_count >= 10               → yellow
        # 6. иначе                                → green
        if red_count >= RED_ESCALATION_THRESHOLD:
            color = "red"
        elif red_count > 0 and (red_count + yellow_count) >= RED_ESCALATION_THRESHOLD:
            color = "red"
        elif red_count >= RED_MIN_THRESHOLD:
            color = "red"
        elif yellow_count >= 5:
            color = "yellow"
        elif escalation_count >= GREEN_ESCALATION_THRESHOLD:
            color = "yellow"
        else:
            color = "green"

        logger.debug(f"{d}: {color} (red={red_count}, yellow={yellow_count}, escalation={escalation_count})")
        days_with_matches[d.strftime("%d.%m.%Y")] = color

    # Все дни месяца — без матчей получают green
    days_in_month = _calendar.monthrange(year, month)[1]
    day_colors: Dict[str, str] = {}
    for day_num in range(1, days_in_month + 1):
        d_str = date(year, month, day_num).strftime("%d.%m.%Y")
        day_colors[d_str] = days_with_matches.get(d_str, "green")

    logger.info(f"Цветов дней рассчитано: {len(day_colors)} | "
                f"red={(  list(day_colors.values()).count('red'))} "
                f"yellow={(list(day_colors.values()).count('yellow'))} "
                f"green={ (list(day_colors.values()).count('green'))}")
    return day_colors


# ---------------------------------------------------------------------------
# Запись status.csv
# ---------------------------------------------------------------------------

def _write_status_csv(day_colors: Dict[str, str], year: int, month: int,
                      base_dir: Optional[str] = None):
    """
    Записывает base_dir/data/YYYY/MM/MM.YYYY_status.csv
    Формат:
        date;color
        01.03.2026;yellow
        02.03.2026;red
    """
    path = _status_path(year, month, base_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    sorted_days = sorted(
        day_colors.items(),
        key=lambda x: datetime.strptime(x[0], "%d.%m.%Y")
    )

    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["date", "color"])
        for day_str, color in sorted_days:
            writer.writerow([day_str, color])

    logger.info(f"Status записан → {path} ({len(sorted_days)} дней)")


# ---------------------------------------------------------------------------
# Сохранение filtered.xlsx
# ---------------------------------------------------------------------------

def _save_filtered(filtered_df: pd.DataFrame, year: int, month: int,
                   base_dir: Optional[str] = None) -> str:
    path = get_filtered_path(year, month, base_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    out_df = filtered_df[[c for c in filtered_df.columns
                           if not c.startswith("_")]].copy()
    out_df.to_excel(path, index=False, engine="openpyxl")
    logger.info(f"Filtered сохранён → {path} ({len(out_df):,} строк)")
    return path


# ---------------------------------------------------------------------------
# Публичный API: add_tournament
# ---------------------------------------------------------------------------

def add_tournament(
    full_name: str,
    short_name: str = "",
    color: str = "",
    base_dir: Optional[str] = None,
    year: Optional[int] = None,
    month: Optional[int] = None,
    rebuild_filtered: bool = True
) -> bool:
    """
    Добавляет турнир в tournaments.csv.
    Если указан year/month — дообогащает filtered.xlsx и пересчитывает status.csv.

    Аргументы:
        full_name        — полное название (ключ фильтра)
        short_name       — короткое название
        color            — цвет: red/yellow/green или Красный/Желтый/Зеленый
        base_dir         — корень проекта
        year, month      — период для дообогащения
        rebuild_filtered — пересчитать filtered+status после добавления

    Возвращает True если добавлен, False если уже существует.
    """
    t_path = _tournaments_path(base_dir)

    if os.path.exists(t_path):
        df_t = pd.read_csv(t_path, sep=None, engine="python", dtype=str)
        existing = df_t.iloc[:, 0].astype(str).str.strip().str.lower().tolist()
    else:
        df_t = pd.DataFrame(columns=["full", "short", "color"])
        existing = []

    if full_name.strip().lower() in existing:
        logger.warning(f"Турнир уже существует в tournaments.csv: {full_name!r}")
        return False

    new_row = {
        "full":  full_name.strip(),
        "short": short_name.strip() or full_name.strip(),
        "color": color.strip(),
    }
    df_t = pd.concat([df_t, pd.DataFrame([new_row])], ignore_index=True)
    df_t.to_csv(t_path, index=False, encoding="utf-8")
    logger.info(f"Турнир добавлен → {full_name!r} / {short_name!r} / {color!r}")

    if rebuild_filtered and year and month:
        logger.info(f"Дообогащение filtered за {month:02d}.{year}...")
        try:
            matches_df    = _load_matches(year, month, base_dir)
            tournaments_df = _load_tournaments(base_dir)
            filtered_path  = get_filtered_path(year, month, base_dir)

            new_matches = matches_df[
                matches_df["tournament"].apply(lambda t: _is_match(t, full_name))
            ]

            if new_matches.empty:
                logger.info(f"Новых матчей для {full_name!r} не найдено")
            else:
                logger.info(f"Добавляется {len(new_matches)} матчей для {full_name!r}")
                if os.path.exists(filtered_path):
                    existing_filtered = pd.read_excel(
                        filtered_path, dtype=str, engine="openpyxl"
                    )
                    combined = pd.concat(
                        [existing_filtered, new_matches], ignore_index=True
                    ).drop_duplicates()
                else:
                    combined = new_matches

                _save_filtered(combined, year, month, base_dir)
                day_colors = _compute_day_colors(combined, tournaments_df, year, month)
                _write_status_csv(day_colors, year, month, base_dir)

        except Exception as e:
            logger.exception(f"Ошибка дообогащения filtered: {e}")

    return True


# ---------------------------------------------------------------------------
# Основная функция
# ---------------------------------------------------------------------------

def run_filter(month_str: str, base_dir: Optional[str] = None) -> str:
    """
    Полный цикл анализа и фильтрации матчей за месяц.

    Аргументы:
        month_str — "03.2026"
        base_dir  — корень проекта (по умолчанию директория скрипта)

    Возвращает путь к filtered файлу.
    """
    try:
        dt = datetime.strptime(month_str, "%m.%Y")
        year, month = dt.year, dt.month
    except ValueError:
        raise ValueError(f"Неверный формат: '{month_str}'. Ожидается MM.YYYY")

    logger.info("=" * 60)
    logger.info(f"Анализ матчей за {month:02d}.{year}")
    logger.info("=" * 60)

    # --- Загрузка ---
    matches_df     = _load_matches(year, month, base_dir)
    tournaments_df = _load_tournaments(base_dir)
    total          = len(matches_df)

    # --- Фильтрация ---
    logger.info("Запуск фильтрации...")
    filtered_df, matched, skipped, potential = _filter_matches(matches_df, tournaments_df)

    # --- Лог прошедших ---
    logger.info(f"Результат: {len(filtered_df):,} / {total:,} матчей оставлено")
    logger.info(f"Турниры прошедшие фильтр ({len(matched)}):")
    counts = matches_df["tournament"].value_counts().to_dict()
    for name in matched:
        logger.info(f"  ✓ [{counts.get(name, 0):4d} матч.]  {name}")

    # --- Лог скипнутых ---
    logger.info(f"Скипнутые турниры ({len(skipped)}):")
    for name in skipped:
        logger.info(f"  ✗ [{counts.get(name, 0):4d} матч.]  {name}")

    # --- Потенциально важные ---
    if potential:
        logger.info("─" * 50)
        logger.info(f"⚑  ПОТЕНЦИАЛЬНО ВАЖНЫЕ ({len(potential)}) — не в фильтре:")
        logger.info("   score = доля совпавших слов с эталонами")
        for name, score, cnt in potential:
            logger.info(f"  ?  score={score:.2f}  [{cnt:4d} матч.]  {name}")
        logger.info("─" * 50)
        logger.info("  → используй add_tournament(name, ...) для добавления")
    else:
        logger.info("Потенциально важных турниров не обнаружено")

    # --- Нагрузка по дням ---
    logger.info("Расчёт нагрузки по дням...")
    day_colors = _compute_day_colors(filtered_df, tournaments_df, year, month)

    icons = {"red": "🔴", "yellow": "🟡", "green": "🟢"}
    logger.info("Нагрузка по дням:")
    for day_str, color in sorted(day_colors.items(),
                                  key=lambda x: datetime.strptime(x[0], "%d.%m.%Y")):
        logger.info(f"  {icons.get(color,'⚪')} {day_str} → {color}")

    # --- Сохранение ---
    _write_status_csv(day_colors, year, month, base_dir)
    out_path = _save_filtered(filtered_df, year, month, base_dir)

    logger.info("=" * 60)
    logger.info(f"Готово → {out_path}")
    logger.info(f"  Всего матчей:      {total:,}")
    logger.info(f"  После фильтрации:  {len(filtered_df):,}")
    logger.info(f"  Скипнуто турниров: {len(skipped)}")
    logger.info(f"  Дней с нагрузкой:  {len(day_colors)}")
    logger.info("=" * 60)

    return out_path


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    month_arg = sys.argv[1] if len(sys.argv) > 1 else "04.2026"
    logger.info(f"Запуск: month={month_arg}")
    try:
        result = run_filter(month_arg)
        print(f"\nФайл создан: {result}")
    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Ошибка: {e}")
        sys.exit(1)