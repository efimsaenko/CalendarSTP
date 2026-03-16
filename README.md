# Sports Calendar Bot 🏆

Telegram-бот для автоматического сбора, фильтрации и отображения спортивных событий.
Парсит расписание матчей с championat.com через JSON API, анализирует нагрузку по дням и формирует Excel-календари.

---

## Быстрый старт

```bash
git clone https://github.com/efikk/CalendarJoger.git
cd CalendarJoger
pip install aiogram apscheduler openpyxl pandas
```

Положить рядом с кодом:
- `Календарь_Событий.xlsx` — шаблон Excel-календаря
- `tournaments.csv` — реестр турниров
- `config.txt` — токен и настройки

```bash
python DailyTG.py
```

---

## Компоненты

```
DailyTG.py              — точка входа: запуск бота, планировщик, shutdown
BotHandlers.py          — все команды бота и scheduled jobs
BotUsers.py             — автоматический реестр пользователей (users.json)
DailyPipeline.py        — синхронный пайплайн одного дня
MonthPipeline.py        — оркестратор месячного пайплайна
ChampionatGrabber.py    — HTTP-парсер расписания с championat.com (JSON API)
DailyFilter.py          — фильтрация матчей по tournaments.csv
DailyOutput.py          — форматирование сообщения для Telegram
MonthGrabbScheduler.py  — парсер всего месяца (обёртка над ChampionatGrabber)
MonthMatchFilter.py     — анализ месяца: цвета дней, status.csv, filtered.xlsx
MonthCalendarExcel.py   — генератор Excel-календаря на основе шаблона
logger.py               — JSON-логгер (однострочные записи)
tournaments.csv         — реестр турниров (фильтр + цвета + сокращения)
config.txt              — конфигурация бота
Календарь_Событий.xlsx  — шаблон Excel-календаря
```

---

## Структура данных

```
data/
└── YYYY/
    └── MM/
        ├── matches_YYYY_MM.xlsx       — все матчи месяца (MonthGrabbScheduler)
        ├── MM.YYYY_filtered.xlsx      — матчи прошедшие фильтр (MonthMatchFilter)
        ├── MM.YYYY_status.csv         — цвет каждого дня: date;color
        ├── MM.YYYY_calendar.xlsx      — готовый Excel-календарь (MonthCalendarExcel)
        ├── matches_YYYY-MM-DD.csv     — дневные матчи (ChampionatGrabber, кэш)
        └── filtered_YYYY-MM-DD.csv   — дневные отфильтрованные матчи (DailyPipeline, кэш)

logs/
└── YYYY-MM-DD.json.log               — JSON-лог за день

users.json                            — реестр пользователей (BotUsers, авто)
```

---

## Карта взаимодействия

```
DailyTG.py (бот)
│
├── /today, /date
│       BotHandlers → DailyPipeline.run()
│           ├── ChampionatGrabber   → matches[]
│           ├── DailyFilter         → filtered_df
│           └── DailyOutput         → text (HTML) → Telegram
│
├── /month MM.YYYY
│       BotHandlers → MonthPipeline.run_month_pipeline()
│           ├── MonthGrabbScheduler
│           │       └── ChampionatGrabber × N дней → matches_YYYY_MM.xlsx
│           ├── MonthMatchFilter
│           │       └── MM.YYYY_filtered.xlsx + MM.YYYY_status.csv
│           └── MonthCalendarExcel
│                   └── MM.YYYY_calendar.xlsx → Telegram
│
└── Scheduler
        ├── 9:00 daily  → scheduled_daily()  — рассылка всем
        ├── 19-е 9:00   → scheduled_19th()   — следующий месяц
        └── 5-е  9:00   → scheduled_5th()    — обновление + diff
```

---

## Пайплайны подробно

### Ежедневный пайплайн (/today, /date, scheduler 9:00)

```
Пользователь → /today или /date DD.MM.YYYY
    │
    ▼
BotHandlers._run_daily(date_str)
    └── asyncio.to_thread → DailyPipeline.run(date_str, request_id, force_grab)
            │
            ├── [кэш есть, force=False]
            │       читает: data/YYYY/MM/filtered_YYYY-MM-DD.csv
            │       → пропускает парсинг
            │
            └── [кэш нет или force=True]
                    │
                    ├── ChampionatGrabber.grab(date_str)
                    │       GET https://www.championat.com/stat/data/YYYY-MM-DD
                    │       парсит JSON: матчи по всем видам спорта
                    │       возвращает: [{tournament, date, time, participants, stage}]
                    │       пишет:      data/YYYY/MM/matches_YYYY-MM-DD.csv
                    │
                    ├── DailyFilter.filter_matches_by_tournaments(matches_df, tournaments_df)
                    │       читает:    tournaments.csv
                    │       фильтрует: оставляет только турниры из реестра
                    │       возвращает: filtered_df
                    │       пишет:      data/YYYY/MM/filtered_YYYY-MM-DD.csv
                    │
                    └── DailyOutput.format_output(filtered_df, date_str, ...)
                            читает:  MM.YYYY_status.csv → иконка дня
                            строит:  HTML для Telegram
                            пример:  "🟡 07.03.2026 — АПЛ, РПЛ
                                      17:00  Ман Сити – Ливерпуль
                                      19:30  ЦСКА – Зенит"
                            → BotHandlers._broadcast_text → bot.send_message() всем
```

### Месячный пайплайн (/month, scheduler 19-е и 5-е)

```
Пользователь → /month MM.YYYY
    │
    ├── [calendar.xlsx уже есть] → bot.send_document(calendar.xlsx)   кэш
    │
    └── [нет]
            ▼
    BotHandlers._run_month(month_str)
        └── asyncio.to_thread → MonthPipeline.run_month_pipeline(month_str, base_dir)
                │
                ├── ШАГ 1: MonthGrabbScheduler.run_month(year, month)
                │       для каждого дня месяца:
                │           ChampionatGrabber.grab(date_str, save_csv=False)
                │           → [{tournament, date, time, participants, stage}]
                │       пишет: data/YYYY/MM/matches_YYYY_MM.xlsx
                │                 лист "matches":
                │                   tournament | date | time | participants | stage | request_id
                │                 лист "daily_summary":
                │                   date | matches_count | status | request_id | ts
                │
                ├── ШАГ 2: MonthMatchFilter.run_filter(month_str, base_dir)
                │       читает:    matches_YYYY_MM.xlsx + tournaments.csv
                │       фильтрует: _is_match(tournament_name, reference)
                │       считает цвета дней:
                │           red_count >= 3                      → red
                │           red_count > 0 и red+yellow >= 3     → red
                │           red_count > 0                        → yellow
                │           yellow_count >= 5                    → yellow
                │           escalation_count >= 10               → yellow
                │           иначе                                → green
                │       пишет: data/YYYY/MM/MM.YYYY_filtered.xlsx
                │                 tournament | date | time | participants | stage
                │              data/YYYY/MM/MM.YYYY_status.csv
                │                 date;color
                │
                └── ШАГ 3: MonthCalendarExcel.create_month_calendar(month_str, base_dir)
                        читает: Календарь_Событий.xlsx   — шаблон
                                MM.YYYY_status.csv        — цвета ячеек
                                MM.YYYY_filtered.xlsx     — контент + лист Детально
                                tournaments.csv           — короткие названия
                        строит:
                          Лист 1 "Календарь спорт. активности":
                            A2 = год, B2 = месяц
                            строки 4-15: 6 недель × 7 дней (дата + контент)
                            покраска: красный/жёлтый/зелёный по status.csv
                            контент:  "АПЛ, КХЛ, Чемпионаты Испании, Германии"
                          Лист 2 "Детально":
                            все матчи: tournament | date | time | participants
                            отсортированы по дате и времени
                        пишет: data/YYYY/MM/MM.YYYY_calendar.xlsx
                        → BotHandlers._broadcast_document → bot.send_document() всем
```

### Расписание

| Триггер | Функция | Действие | При пропуске |
|---------|---------|----------|--------------|
| Каждый день 9:00 | scheduled_daily | Дневная рассылка всем пользователям | Пропускается |
| 19-е число 9:00 | scheduled_19th | Сбор следующего месяца → рассылка | Запускается при старте |
| 5-е число 9:00 | scheduled_5th | Перепарсинг текущего месяца + diff цветов → рассылка | Запускается при старте |

---

## Пользователи (BotUsers)

Реестр ведётся автоматически в `users.json`. Каждый пользователь регистрируется при первом обращении к боту — никакой ручной настройки не нужно. Все рассылки идут всем зарегистрированным пользователям.

```json
{
  "356119356": {
    "username": "efikk",
    "first_seen": "2026-03-14T18:00:00Z",
    "last_seen":  "2026-03-14T20:14:11Z"
  }
}
```

---

## Логирование (logger.py)

Каждая запись — одна строка JSON. Лог пишется одновременно в файл и stdout.

```
logs/YYYY-MM-DD.json.log
```

Пример записи:

```json
{
  "timestamp": "2026-03-14T20:14:11Z",
  "level": "INFO",
  "module": "DailyPipeline",
  "message": "pipeline done",
  "request_id": "44f6e76122cd",
  "user_id": 356119356,
  "username": "efikk"
}
```

| Поле | Назначение |
|------|-----------|
| timestamp | UTC время события |
| level | INFO / WARNING / ERROR |
| module | Имя модуля-источника |
| message | Текст события |
| request_id | Уникальный ID запроса (12 hex) — сквозной через все модули |
| user_id | Telegram ID пользователя (если применимо) |
| username | Telegram username (если применимо) |
| alert | true — критическое событие требующее внимания |
| exc | Трейсбек исключения в одну строку (если было) |

---

## Команды бота

### Пользовательские

| Команда | Описание |
|---------|----------|
| /today | Расписание на сегодня |
| /date 07.03.2026 | Расписание на конкретную дату |
| /month 03.2026 | Excel-календарь за месяц (из кэша или новый) |

### Администраторские

| Команда | Описание |
|---------|----------|
| /add Full / Short / Color / Escalation | Добавить турнир в реестр |
| /delete 07.03.2026 | Удалить кэш дневного отчёта |
| /deleteMonth 03.2026 | Удалить кэш месячного календаря |
| /users | Список всех зарегистрированных пользователей |

---

## tournaments.csv

```
tournament;short;importants;escalation
Англия — Премьер-лига.;АПЛ;Зеленый;1
Российская Премьер-лига;РПЛ;Зеленый;1
Испания — Примера.;Чемпионат Испании;Зеленый;1
Лига чемпионов.;Лига Чемпионов;Красный;0
```

| Колонка | Назначение |
|---------|-----------|
| tournament | Полное название — ключ для сопоставления (вхождение подстроки) |
| short | Краткое название в Telegram и Excel |
| importants | Цвет нагрузки дня: Красный / Желтый / Зеленый |
| escalation | 1 = матчи влияют на green → yellow эскалацию |

---

## config.txt

```
BOT_TOKEN=ваш_токен
ADMIN_CHAT_ID=123456789
USER_LIMIT=10
```

---

## Зависимости между модулями

```
DailyTG.py
    ├── BotHandlers.py
    │       ├── DailyPipeline.py
    │       │       ├── ChampionatGrabber.py
    │       │       ├── DailyFilter.py
    │       │       └── DailyOutput.py
    │       ├── MonthPipeline.py
    │       │       ├── MonthGrabbScheduler.py
    │       │       │       └── ChampionatGrabber.py
    │       │       ├── MonthMatchFilter.py
    │       │       └── MonthCalendarExcel.py
    │       └── BotUsers.py
    └── logger.py

tournaments.csv  — читают: DailyFilter, DailyOutput, MonthMatchFilter, MonthCalendarExcel
data/            — пишут и читают все модули
users.json       — BotUsers (авто)
logs/            — logger.py (авто)
```

---

*Сделано [@efikk](https://t.me/efikk)*