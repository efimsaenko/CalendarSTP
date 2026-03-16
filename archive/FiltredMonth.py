import os
import pandas as pd
from datetime import datetime, timedelta
from calendar import month_name

# Папка с TXT-файлами турниров
TOURNAMENTS_DIR = "tournaments"


def get_next_month_year():
    today = datetime.today()
    next_month = today.replace(day=28) + timedelta(days=4)  # гарантированно переходим на следующий месяц
    year = next_month.year
    month = next_month.month
    return month, year


def load_tournaments():
    tournaments_set = set()
    if not os.path.exists(TOURNAMENTS_DIR):
        raise FileNotFoundError(
            f"Папка '{TOURNAMENTS_DIR}' не найдена. Создайте и положите туда TXT файлы с турнирами.")
    for fname in os.listdir(TOURNAMENTS_DIR):
        if fname.lower().endswith(".txt"):
            with open(os.path.join(TOURNAMENTS_DIR, fname), encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        tournaments_set.add(line)
    return tournaments_set


def filter_matches(csv_path, tournaments_set):
    df = pd.read_csv(csv_path)

    # Фильтруем все строки, где хотя бы один ключ турнира содержится в названии турнира матча
    mask = df['tournament'].apply(lambda x: any(t in x for t in tournaments_set))
    filtered_df = df[mask]
    return filtered_df


def main():
    month, year = get_next_month_year()
    month_name_str = month_name[month].lower()  # пример: "november"

    csv_filename = f"matches_{month_name_str}_{year}.csv"
    if not os.path.exists(csv_filename):
        raise FileNotFoundError(f"CSV-файл за {month_name_str} {year} не найден: {csv_filename}")

    tournaments_set = load_tournaments()
    filtered_df = filter_matches(csv_filename, tournaments_set)

    output_dir = f"filtered_{month_name_str}_{year}"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"filtered_matches_{month_name_str}_{year}.csv")

    filtered_df.to_csv(output_path, index=False, encoding="utf-8")
    print(f"Фильтрованные данные сохранены в {output_path}")


if __name__ == "__main__":
    main()
