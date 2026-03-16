import os
import pandas as pd
import logging

logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s'
)
import re

def normalize_for_match(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = s.replace("\ufeff", "")      # BOM
    s = s.replace("\xa0", " ")       # NBSP
    s = s.replace("\u200b", "")      # zero-width space
    s = s.replace("–", "-").replace("—", "-")  # тире → дефис
    s = s.strip()
    # убрать номера туров (пример: . 29-й тур, / 1/2 финала)
    s = re.sub(r'\s*\d+[-/].*$', '', s)
    return s

# ---------- LOAD CSV ----------

def load_csv_auto(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Файл не найден: {path}")
    try:
        df = pd.read_csv(path, sep=None, engine="python", encoding="utf-8-sig")
        df.columns = df.columns.str.strip()  # убираем BOM и лишние пробелы
    except Exception as e:
        raise ValueError(f"Не удалось прочитать CSV {path}: {e}")
    return df


def load_tournaments(path: str) -> pd.DataFrame:
    df = load_csv_auto(path)
    if "tournament" not in df.columns:
        raise ValueError(f"Файл турниров должен содержать колонку 'tournament', найдено: {df.columns.tolist()}")
    logging.info(f"Загружено турниров в CSV: {len(df)}")
    return df


# ---------- FILTER ----------

def filter_matches_by_tournaments(matches_df: pd.DataFrame, tournaments_df: pd.DataFrame) -> pd.DataFrame:
    """
    Фильтрует матчи по турнирам из CSV.
    - Берёт уникальные турниры из дня
    - Сравнивает с турнирами CSV (простое включение)
    - Добавляет все матчи, которые содержат хотя бы один тур из CSV
    - Всегда возвращает DataFrame
    """
    filtered_rows = []

    # Обрезаем пробелы в названиях турниров CSV
    tournaments_list = tournaments_df['tournament'].dropna().map(str.strip).unique().tolist()
    logging.info(f"Турниров в файле tournaments.csv: {len(tournaments_list)}")

    # Уникальные турниры дня
    unique_match_tournaments = matches_df['tournament'].dropna().map(str.strip).unique().tolist()
    logging.info(f"Уникальных турниров в дне: {len(unique_match_tournaments)}")

    # Находим реально используемые турниры
    tournaments_for_filter = []
    for match_name in unique_match_tournaments:
        for tour_name in tournaments_list:
            if tour_name in match_name:
                if tour_name not in tournaments_for_filter:
                    tournaments_for_filter.append(tour_name)
                logging.info(f"[FOUND] '{match_name}' содержит '{tour_name}'")
                break
        else:
            logging.warning(f"[NO MATCH] Уникальный турнир дня не найден в CSV: '{match_name}'")

    logging.info(f"Турниров для фильтрации (найдено в CSV): {len(tournaments_for_filter)}")

    # Фильтруем все матчи
    for idx, row in matches_df.iterrows():
        match_name = str(row['tournament']).strip()
        match_added = False
        for tour_name in tournaments_for_filter:
            if tour_name in match_name:
                filtered_rows.append(row.to_dict())
                logging.info(f"[MATCH] '{match_name}' добавлен для турнира '{tour_name}'")
                match_added = True
                break  # добавляем один раз на матч
        if not match_added:
            pass

    # Создаём DataFrame
    filtered_df = pd.DataFrame(filtered_rows)

    # Если пусто — возвращаем пустой DataFrame с колонками исходного matches_df
    if filtered_df.empty:
        logging.warning("Фильтрованные матчи пустые, возвращаю пустой DataFrame")
        filtered_df = matches_df.iloc[0:0].copy()

    logging.info(f"Матчей после фильтрации: {len(filtered_df)}")
    return filtered_df

# ---------- MAIN ----------

def main(date_str: str):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, "data")
    os.makedirs(data_dir, exist_ok=True)

    matches_file = os.path.join(data_dir, f"matches_{date_str}.csv")
    tournaments_file = os.path.join(base_dir, "tournaments.csv")
    output_file = os.path.join(data_dir, f"filtered_{date_str}.csv")

    if not os.path.exists(matches_file):
        logging.error(f"Файл матчей не найден: {matches_file}")
        return

    try:
        matches_df = load_csv_auto(matches_file)
    except Exception as e:
        logging.error(f"Не удалось загрузить файл матчей: {e}")
        return

    logging.info(f"Загружено матчей: {len(matches_df)}")
    if matches_df.empty:
        logging.warning("Файл матчей пустой")
        return

    try:
        tournaments_df = load_tournaments(tournaments_file)
    except Exception as e:
        logging.error(f"Не удалось загрузить tournaments.csv: {e}")
        return

    filtered_df = filter_matches_by_tournaments(matches_df, tournaments_df)

    filtered_df.to_csv(output_file, index=False, encoding="utf-8-sig")
    logging.info(f"Фильтрованные матчи сохранены: {output_file}")


if __name__ == "__main__":
    main("2026-03-12")