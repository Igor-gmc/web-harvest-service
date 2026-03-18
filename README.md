# Web Harvest Service

Сервис для автоматического сбора данных о банкротстве с сайтов [fedresurs.ru](https://fedresurs.ru) и [kad.arbitr.ru](https://kad.arbitr.ru) по списку ИНН из Excel-файла.

## Стек

- **Python 3.11** + asyncio
- **Playwright** — браузерная автоматизация через CDP
- **PostgreSQL 16** + SQLAlchemy 2.0 (async) + Alembic
- **Pydantic Settings** — конфигурация из `.env`
- **Docker Compose** — PostgreSQL

## Быстрый старт

### 1. Зависимости

```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
playwright install chromium
```

### 2. PostgreSQL

```bash
docker compose up -d
```

### 3. Миграции

```bash
alembic upgrade head
```

### 4. Входные данные

Положить Excel-файл со списком ИНН в `input/identifiers.xlsx`.
Первая колонка — ИНН, таблица без заголовков (читаются все строки).

### 5. Запуск

```bash
python -m src.main
```

## Pipeline

Приложение при старте выполняет двухпроходный pipeline:

**Проход 1 — fedresurs:**
1. Проверяет подключение к БД
2. Импортирует ИНН из Excel в таблицу задач
3. Импортирует kad_arbitr задачи из результатов fedresurs (пока пусто)
4. Восстанавливает зависшие задачи (recovery)
5. Обрабатывает все pending задачи (fedresurs)

**Проход 2 — kad.arbitr:**
6. Импортирует kad_arbitr задачи из `fedresurs_results.case_number`
7. Обрабатывает все pending kad_arbitr задачи

### Детекция изменений файла

При каждом запуске сравнивается набор ИНН из Excel с набором в БД:
- **Файл не изменился** — пропускает уже обработанные задачи, повторяет только failed
- **Файл изменился** (добавлен/удалён/изменён ИНН) — полный сброс: удаляет все задачи и результаты обоих типов, парсит заново с нуля

## Архитектура

```
src/
├── main.py                  # Точка входа, startup pipeline
├── core/
│   ├── config.py            # Pydantic Settings из .env
│   ├── enums.py             # TaskStatus, TaskType, CheckpointStep, ErrorType
│   └── logger.py            # Логирование: stdout + файл
├── db/
│   ├── models.py            # SQLAlchemy модели (5 таблиц)
│   ├── repositories.py      # Все DB-операции
│   └── session.py           # AsyncSession factory
├── schemas/
│   ├── input.py             # InputRow, ExcelReadResult
│   ├── results.py           # FedresursResultData
│   └── kad_result.py        # KadArbitrResultData
├── services/
│   ├── excel_reader.py      # Чтение и валидация Excel
│   ├── task_service.py      # import, complete, fail, not_found, recover
│   ├── task_executor.py     # Оркестрация: heartbeat → parse → save → complete
│   └── worker_runner.py     # acquire → execute → reuse page loop
├── browser/
│   ├── factory.py           # BrowserFactory (CDP)
│   ├── page_helpers.py      # detect_block, find_element, human_delay, screenshots
│   └── selectors.py         # CSS-селекторы fedresurs.ru и kad.arbitr.ru
└── parsers/
    ├── base.py              # BaseParser (ABC)
    ├── fedresurs.py         # FedresursParser
    └── kad_arbitr.py        # KadArbitrParser
```

### Два парсера — один паттерн

Оба парсера следуют одному архитектурному паттерну, но каждый знает только свой сайт:

| | FedresursParser | KadArbitrParser |
|---|---|---|
| **Вход** | ИНН из Excel | Номер дела из `fedresurs_results` |
| **Сайт** | fedresurs.ru | kad.arbitr.ru |
| **Результат** | case_number + last_publication_date | document_date + document_name + PDF URL |
| **Таблица** | `fedresurs_results` | `kad_arbitr_results` |

### Переиспользование вкладки

Вкладка браузера **не закрывается** между задачами одного типа — это экономит время и снижает нагрузку:

- **Успешный парсинг** — парсер кликает логотип для возврата на главную, вводит следующий запрос
- **"Ничего не найдено"** — вкладка остаётся на странице, поле очищается, вводится следующий запрос
- **Ошибка** — вкладка закрывается, для следующей задачи открывается новая
- **Смена task_type** — при переходе от fedresurs к kad_arbitr (или наоборот) вкладка освобождается, открывается новая для другого сайта

### Имитация поведения пользователя (human_delay)

Все паузы между действиями выполняются со **случайной задержкой** `random.uniform(1, HUMAN_DELAY_MAX_SECONDS)`.

```env
HUMAN_DELAY_MAX_SECONDS=10
```

### Lifecycle задачи

```
pending ──→ in_progress ──→ done
                │
                ├──→ not_found (ИНН не найден / нет данных / пустая хронология)
                │
                ├──→ failed
                │
                └──→ resume_pending (recovery зависших)
                        │
                        └──→ in_progress (повторная обработка)
```

- **Lock-based ownership**: `locked_by`, `lock_expires_at`, `worker_name`
- **Heartbeat**: воркер периодически продлевает `lock_expires_at`
- **Recovery**: при старте находит `in_progress` задачи с просроченным lock и возвращает в очередь
- **Приоритет**: `resume_pending` обрабатывается раньше `pending`

### Separation of Concerns

| Слой | Ответственность |
|------|----------------|
| **Worker** | Берёт задачу из очереди, управляет переиспользованием вкладки |
| **Executor** | Heartbeat + выбор парсера + сохранение результата + завершение |
| **Parser** | Только получение данных (ничего не знает про БД и lifecycle) |
| **BrowserFactory** | Управление Chrome (запуск, подключение, закрытие) |

## Проблема с Chrome и как её решили

### Симптом

При запуске Playwright для парсинга fedresurs.ru сайт возвращал **403 Forbidden** — независимо от режима браузера, движка и User-Agent. При этом **обычный Chrome** открывал сайт без проблем.

### Решение: CDP (Chrome DevTools Protocol)

Вместо Playwright-запуска Chrome (с automation-флагами) мы:

1. **Запускаем Chrome сами** через `subprocess.Popen` с минимальными флагами — без `--enable-automation`
2. **Подключаем Playwright через CDP** — полный контроль при чистом fingerprint
3. **Автоматический lifecycle** через `BrowserFactory`

## Конфигурация (.env)

```env
# Приложение
APP_NAME=bankruptcy_parser
APP_ENV=dev
LOG_LEVEL=INFO

# База данных
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/bankruptcy_parser

# Входные файлы
INPUT_XLSX_PATH=input/identifiers.xlsx

# Браузер
PLAYWRIGHT_HEADLESS=true
BROWSER_TIMEOUT_MS=30000
CDP_PORT=9222
MAX_BROWSER_PAGES=3

# Имитация пользователя
HUMAN_DELAY_MAX_SECONDS=10

# Блокировки и heartbeat
LOCK_TTL_SECONDS=60
HEARTBEAT_INTERVAL_SECONDS=15
```

## Требования

- **Python** 3.11+
- **Google Chrome** установлен в системе
- **PostgreSQL** 16 (через Docker или локально)
- **Playwright** + Chromium (`playwright install chromium`)

## Текущий статус

- [x] Каркас проекта, Docker, конфиг
- [x] БД: модели, миграции, репозитории
- [x] Excel reader с валидацией ИНН (без заголовков)
- [x] Импорт задач с детекцией изменений файла
- [x] Lifecycle задачи: acquire, heartbeat, complete/fail/not_found
- [x] Recovery зависших задач
- [x] Browser layer (CDP, обход WAF)
- [x] FedresursParser: поиск по ИНН, извлечение case_number + дата публикации
- [x] KadArbitrParser: поиск по номеру дела, извлечение даты + названия документа + PDF
- [x] Двухпроходный pipeline: fedresurs → kad.arbitr (из результатов fedresurs)
- [x] Переиспользование вкладки (с корректным сбросом при смене сайта)
- [x] Имитация пользователя (random задержки между этапами)
- [x] Worker loop (обработка всех задач)
- [ ] Retry-механика
- [ ] Proxy support
