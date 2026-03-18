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
Первая колонка — ИНН, первая строка — заголовок (пропускается).

### 5. Запуск

```bash
python -m src.main
```

Приложение при старте:
1. Проверяет подключение к БД
2. Импортирует ИНН из Excel в таблицу задач (идемпотентно)
3. Восстанавливает зависшие задачи (recovery)
4. Берёт следующую задачу и выполняет парсинг

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
│   └── results.py           # FedresursResultData
├── services/
│   ├── excel_reader.py      # Чтение и валидация Excel
│   ├── task_service.py      # import, complete, fail, recover
│   ├── task_executor.py     # Оркестрация: heartbeat → parse → save → complete
│   └── worker_service.py    # acquire → execute
├── browser/
│   ├── factory.py           # BrowserFactory (CDP)
│   ├── page_helpers.py      # detect_block, find_element, screenshots
│   └── selectors.py         # CSS-селекторы fedresurs.ru
└── parsers/
    ├── base.py              # BaseParser (ABC)
    └── fedresurs.py         # FedresursParser
```

### Lifecycle задачи

```
pending ──→ in_progress ──→ done
                │
                ├──→ failed
                │
                └──→ resume_pending (recovery зависших)
                        │
                        └──→ in_progress (повторная обработка)
```

- **Lock-based ownership**: `locked_by`, `lock_expires_at`, `worker_name`
- **Heartbeat**: воркер периодически продлевает `lock_expires_at`, доказывая что жив
- **Recovery**: при старте находит `in_progress` задачи с просроченным lock и возвращает в очередь
- **Приоритет**: `resume_pending` обрабатывается раньше `pending`

### Separation of Concerns

| Слой | Ответственность |
|------|----------------|
| **Worker** | Берёт задачу из очереди |
| **Executor** | Heartbeat + выбор парсера + сохранение результата + завершение |
| **Parser** | Только получение данных (ничего не знает про БД и lifecycle) |
| **BrowserFactory** | Управление Chrome (запуск, подключение, закрытие) |

## Проблема с Chrome и как её решили

### Симптом

При запуске Playwright для парсинга fedresurs.ru сайт возвращал **403 Forbidden** — независимо от:
- Режима браузера (headless / visible)
- Движка (Chromium / Firefox)
- User-Agent
- Persistent profile
- `channel="chrome"` (системный Chrome через Playwright)

При этом **обычный Chrome** (запущенный вручную) открывал сайт без проблем с того же IP.

### Диагностика

1. Сохранение screenshot + HTML при ошибке показало страницу-заглушку CDN с `403 Error`
2. IP на странице блокировки совпадал с реальным IP машины — значит, не гео-блок
3. Firefox тоже получал 403 — значит, не TLS-fingerprint конкретного Chromium
4. `headless=False` тоже 403 — значит, не headless-детекция

**Вывод**: CDN fedresurs.ru определяет Playwright по флагам запуска, которые Playwright добавляет к Chrome: `--enable-automation`, `--remote-debugging-pipe`, `--disable-background-networking` и другие. Эти флаги меняют поведение браузера и детектятся на стороне WAF.

### Решение: CDP (Chrome DevTools Protocol)

Вместо того чтобы позволять Playwright запускать Chrome (с automation-флагами), мы:

1. **Запускаем Chrome сами** через `subprocess.Popen` с минимальными флагами:
   ```
   chrome.exe --remote-debugging-port=9222 --user-data-dir=<temp> --no-first-run
   ```
   Никаких `--enable-automation` — браузер неотличим от обычного.

2. **Подключаем Playwright через CDP**:
   ```python
   browser = await playwright.chromium.connect_over_cdp("http://localhost:9222")
   ```
   Playwright получает полный контроль над вкладками, но fingerprint остаётся чистым.

3. **Прячем окно** на Windows:
   - `--window-position=-32000,-32000` — за пределами экрана
   - `STARTUPINFO` с `SW_MINIMIZE` — окно свёрнуто

4. **Автоматический lifecycle**:
   - `start()` — запускает Chrome, ждёт CDP-порт, подключается
   - `close()` — отключается, `terminate()` Chrome, чистит temp-профиль

Пользователю ничего не нужно делать вручную — `BrowserFactory` управляет всем сам.

### Что не сработало (для справки)

| Подход | Результат |
|--------|-----------|
| Playwright bundled Chromium | 403 |
| Playwright Firefox | 403 |
| `channel="chrome"` (Playwright запускает системный Chrome) | 403 |
| `--headless=new` (новый headless Chrome) | 403 |
| `headless=False` (видимый браузер через Playwright) | 403 |
| Persistent context с профилем | 403 |
| `--disable-blink-features=AutomationControlled` | 403 |
| Подмена `navigator.webdriver` | 403 |
| Реалистичный User-Agent + locale + timezone | 403 |
| **subprocess + CDP (без Playwright-флагов)** | **Работает** |

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
- [x] Excel reader с валидацией ИНН
- [x] Импорт задач (идемпотентный)
- [x] Lifecycle задачи: acquire, heartbeat, complete/fail
- [x] Recovery зависших задач
- [x] Browser layer (CDP, обход WAF)
- [x] FedresursParser: открытие сайта, поиск поля ввода
- [ ] FedresursParser: ввод ИНН, поиск, извлечение данных
- [ ] Retry-механика
- [ ] KadArbitr parser
- [ ] Worker loop (обработка всех задач)
- [ ] Proxy support
