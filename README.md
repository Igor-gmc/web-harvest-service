# Web Harvest Service

Веб-сервис для автоматического сбора данных о банкротстве с сайтов [fedresurs.ru](https://fedresurs.ru) и [kad.arbitr.ru](https://kad.arbitr.ru) по списку ИНН из Excel-файла. Предоставляет веб-интерфейс для загрузки файла, управления парсингом и скачивания результатов.

## Как пользоваться

![Веб-интерфейс](docs/screenshot.png)

1. Откройте веб-интерфейс в браузере (по умолчанию `http://localhost:8000`)
2. Загрузите `.xlsx` файл со списком ИНН (перетащите или нажмите на зону загрузки)
3. Нажмите **Запустить парсинг** — сервис последовательно обработает каждый ИНН:
   - Найдёт номер дела на fedresurs.ru
   - По номеру дела найдёт документы на kad.arbitr.ru
4. Следите за прогрессом в статус-баре (в очереди / в работе / готово / ошибок)
5. Парсинг можно **остановить** и **продолжить** в любой момент
6. После завершения (или на паузе) нажмите **Скачать результаты (.xlsx)**

### Формат входного файла

Файл `.xlsx` без заголовков. Первая колонка — ИНН (10 или 12 цифр). Все строки считываются.

## Стек

- **Python 3.11** + asyncio
- **FastAPI** + Uvicorn — веб-сервер и API
- **Playwright** — браузерная автоматизация через CDP
- **PostgreSQL 16** + SQLAlchemy 2.0 (async) + Alembic
- **Pydantic Settings** — конфигурация из `.env`
- **Docker Compose** — PostgreSQL + приложение + Xvfb

## Запуск

### Вариант 1: Локально

**Требования:** Python 3.11+, Google Chrome, PostgreSQL 16.

```bash
# 1. Виртуальное окружение
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux / macOS

# 2. Зависимости
pip install -r requirements.txt
playwright install chromium

# 3. PostgreSQL (через Docker)
docker compose up -d postgres

# 4. Создать .env (или использовать значения по умолчанию)
cp .env.example .env  # отредактируйте при необходимости

# 5. Миграции
alembic upgrade head

# 6. Запуск веб-сервера
uvicorn src.web.app:app --host 0.0.0.0 --port 8000
```

Откройте `http://localhost:8000` в браузере.

### Вариант 2: Docker (полный сервис)

**Требования:** Docker и Docker Compose.

```bash
# Собрать и запустить всё (приложение + PostgreSQL)
docker compose up -d --build
```

Сервис будет доступен на `http://localhost:8000`. PostgreSQL поднимается автоматически (порт `5433` на хосте, чтобы не конфликтовать с локальным PostgreSQL), миграции применяются при старте контейнера.

**Особенности Docker-окружения:**

- **Xvfb (виртуальный дисплей)** — Chrome запускается в headed-режиме через виртуальный экран (`DISPLAY=:99`), чтобы WAF не детектировал headless-браузер. Xvfb поднимается автоматически через `entrypoint.sh`.
- **shm_size: 512mb** — увеличенный `/dev/shm` для стабильной работы Chrome (по умолчанию Docker даёт 64MB, чего недостаточно — Chrome крашится с "Target crashed").
- **Playwright Chromium** — в Docker используется Chromium из Playwright-бандла (не системный Chrome). `BrowserFactory` автоматически находит его в `~/.cache/ms-playwright/`.
- **`--no-sandbox`** — добавляется автоматически на Linux (Docker работает от root).

Для остановки:

```bash
docker compose down          # остановить контейнеры
docker compose down -v       # остановить и удалить данные БД
```

## Архитектура

```
├── Dockerfile               # Python 3.11 + Playwright + Xvfb
├── entrypoint.sh            # Запуск Xvfb + uvicorn
├── docker-compose.yml       # app + PostgreSQL 16
├── src/
│   ├── main.py              # CLI точка входа (автономный pipeline)
│   ├── web/
│   │   ├── app.py           # FastAPI-приложение, API-эндпоинты
│   │   └── static/
│   │       └── index.html   # Веб-интерфейс (SPA)
│   ├── core/
│   │   ├── config.py        # Pydantic Settings из .env
│   │   ├── enums.py         # TaskStatus, TaskType, CheckpointStep, ErrorType
│   │   └── logger.py        # Логирование: stdout + файл
│   ├── db/
│   │   ├── models.py        # SQLAlchemy модели (5 таблиц)
│   │   ├── repositories.py  # Все DB-операции
│   │   └── session.py       # AsyncSession factory
│   ├── schemas/
│   │   ├── input.py         # InputRow, ExcelReadResult
│   │   ├── results.py       # FedresursResultData
│   │   └── kad_result.py    # KadArbitrResultData
│   ├── services/
│   │   ├── excel_reader.py  # Чтение и валидация Excel
│   │   ├── task_service.py  # import, complete, fail, not_found, recover
│   │   ├── task_executor.py # Оркестрация: heartbeat → parse → save → complete
│   │   └── worker_runner.py # acquire → execute → reuse page loop
│   ├── browser/
│   │   ├── factory.py       # BrowserFactory (CDP, авто-поиск Chrome/Chromium)
│   │   ├── page_helpers.py  # detect_block, find_element, human_delay, screenshots
│   │   └── selectors.py     # CSS-селекторы fedresurs.ru и kad.arbitr.ru
│   └── parsers/
│       ├── base.py          # BaseParser (ABC)
│       ├── fedresurs.py     # FedresursParser
│       └── kad_arbitr.py    # KadArbitrParser
```

### Два режима запуска

| Режим | Команда | Описание |
|-------|---------|----------|
| **Веб-сервер** | `uvicorn src.web.app:app` | FastAPI + веб-интерфейс, управление через браузер |
| **CLI pipeline** | `python -m src.main` | Автономный запуск без UI, парсит весь файл и завершается |

### Два парсера — один паттерн

Оба парсера следуют одному архитектурному паттерну, но каждый знает только свой сайт:

| | FedresursParser | KadArbitrParser |
|---|---|---|
| **Вход** | ИНН из Excel | Номер дела из `fedresurs_results` |
| **Сайт** | fedresurs.ru | kad.arbitr.ru |
| **Результат** | case_number + last_publication_date | document_date + document_name + PDF URL |
| **Таблица** | `fedresurs_results` | `kad_arbitr_results` |

### Параллельная работа парсеров

Stage 1 (fedresurs) и Stage 2 (kad_arbitr) запускаются параллельно в отдельных браузерах (CDP-порты 9222 и 9223). Stage 2 поллит БД, подхватывая номера дел по мере появления результатов от Stage 1.

### Переиспользование вкладки

Вкладка браузера **не закрывается** между задачами одного типа:

- **Успешный парсинг** — парсер возвращается на главную, вводит следующий запрос
- **"Ничего не найдено"** — поле очищается, вводится следующий запрос
- **Ошибка** — вкладка закрывается, для следующей задачи открывается новая

### Lifecycle задачи

```
pending ──→ in_progress ──→ done
                │
                ├──→ not_found
                ├──→ failed
                └──→ resume_pending (recovery) ──→ in_progress
```

- **Lock-based ownership**: `locked_by`, `lock_expires_at`, `worker_name`
- **Heartbeat**: воркер периодически продлевает `lock_expires_at`
- **Recovery**: при старте находит `in_progress` задачи с просроченным lock и возвращает в очередь

### Separation of Concerns

| Слой | Ответственность |
|------|----------------|
| **Web (FastAPI)** | API-эндпоинты, загрузка файлов, статус, скачивание результатов |
| **Worker** | Берёт задачу из очереди, управляет переиспользованием вкладки |
| **Executor** | Heartbeat + выбор парсера + сохранение результата + завершение |
| **Parser** | Только получение данных (ничего не знает про БД и lifecycle) |
| **BrowserFactory** | Управление Chrome (авто-поиск, запуск, CDP-подключение, закрытие) |

## API

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/` | Веб-интерфейс |
| `POST` | `/api/upload` | Загрузка `.xlsx` файла |
| `POST` | `/api/start` | Запуск парсинга |
| `POST` | `/api/stop` | Остановка парсинга |
| `POST` | `/api/resume` | Продолжение парсинга |
| `GET` | `/api/status` | Текущий статус (running, счётчики задач) |
| `GET` | `/api/results` | Результаты в JSON |
| `GET` | `/api/results/download` | Скачать результаты в `.xlsx` |

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

## Проблема с Chrome и как её решили

При запуске Playwright для парсинга fedresurs.ru сайт возвращал **403 Forbidden** — независимо от режима браузера и User-Agent. Обычный Chrome открывал сайт без проблем.

**Решение: CDP (Chrome DevTools Protocol)**

1. Chrome запускается через `subprocess.Popen` без `--enable-automation`
2. Playwright подключается через CDP — полный контроль при чистом fingerprint
3. Автоматический lifecycle через `BrowserFactory`

**В Docker:** headless-режим (`--headless=new`) тоже детектируется WAF. Поэтому в контейнере используется **Xvfb** — виртуальный X-сервер, позволяющий Chrome работать в headed-режиме без реального дисплея. Fingerprint полностью идентичен десктопному запуску.

## Ключевые слова (GitHub Topics)

```
bankruptcy, bankrupt, банкротство, арбитраж, arbitration-court,
fedresurs, kad-arbitr, parser, web-scraper, inn, инн,
конкурсное-производство, реализация-имущества, судебные-акты,
должник, кассация, арбитражные-дела,
playwright, cdp, python, asyncio, fastapi, postgresql,
data-extraction, court-documents, russian-bankruptcy
```

## Текущий статус

- [x] Каркас проекта, Docker, конфиг
- [x] БД: модели, миграции, репозитории
- [x] Excel reader с валидацией ИНН
- [x] Импорт задач с детекцией изменений файла
- [x] Lifecycle задачи: acquire, heartbeat, complete/fail/not_found
- [x] Recovery зависших задач
- [x] Browser layer (CDP, обход WAF)
- [x] FedresursParser: поиск по ИНН, извлечение case_number + дата публикации
- [x] KadArbitrParser: поиск по номеру дела, извлечение даты + названия документа + PDF
- [x] Параллельный pipeline: fedresurs + kad.arbitr одновременно
- [x] Переиспользование вкладки
- [x] Имитация пользователя (random задержки)
- [x] Веб-интерфейс (FastAPI + SPA)
- [x] Docker Compose (приложение + PostgreSQL + Xvfb)
- [x] Docker: Xvfb для обхода headless-детекции WAF
- [x] Docker: авто-поиск Playwright Chromium, shm_size для стабильности
- [ ] Retry-механика
- [ ] Proxy support
