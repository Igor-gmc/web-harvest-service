import asyncio
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import select, func

from src.core.config import BASE_DIR, settings
from src.core.enums import TaskStatus
from src.core.logger import get_logger, setup_logger
from src.db.models import FedresursResult, KadArbitrResult, ParseTask
from src.db.session import async_session

logger = get_logger(__name__)

app = FastAPI(title="Bankruptcy Parser", docs_url=None, redoc_url=None)

STATIC_DIR = Path(__file__).parent / "static"
UPLOAD_DIR = BASE_DIR / "input"


@app.on_event("startup")
async def on_startup():
    setup_logger()
    # Run Alembic migrations via subprocess (env.py uses asyncio.run internally)
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error("Alembic migration failed: %s", result.stderr)
    else:
        logger.info("Alembic migrations applied")

# --- Глобальное состояние парсинга ---
_parsing_state: dict = {
    "running": False,
    "task": None,
    "stop_event": None,
}


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = STATIC_DIR / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    if not file.filename or not file.filename.endswith(".xlsx"):
        raise HTTPException(400, "Only .xlsx files are accepted")

    dest = UPLOAD_DIR / "identifiers.xlsx"
    dest.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx", dir=str(UPLOAD_DIR)) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    # Атомарная замена файла
    Path(tmp_path).replace(dest)
    return {"status": "ok", "filename": file.filename}


@app.post("/api/start")
async def start_parsing():
    if _parsing_state["running"]:
        raise HTTPException(409, "Parsing is already running")

    stop_event = asyncio.Event()
    _parsing_state["stop_event"] = stop_event
    _parsing_state["running"] = True

    task = asyncio.create_task(_run_parsing(stop_event))
    _parsing_state["task"] = task
    task.add_done_callback(_on_parsing_done)

    return {"status": "started"}


@app.post("/api/stop")
async def stop_parsing():
    if not _parsing_state["running"]:
        raise HTTPException(409, "Parsing is not running")

    if _parsing_state["stop_event"]:
        _parsing_state["stop_event"].set()

    return {"status": "stopping"}


@app.post("/api/resume")
async def resume_parsing():
    if _parsing_state["running"]:
        raise HTTPException(409, "Parsing is already running")

    stop_event = asyncio.Event()
    _parsing_state["stop_event"] = stop_event
    _parsing_state["running"] = True

    task = asyncio.create_task(_run_parsing(stop_event, resume=True))
    _parsing_state["task"] = task
    task.add_done_callback(_on_parsing_done)

    return {"status": "resumed"}


@app.get("/api/status")
async def get_status():
    async with async_session() as session:
        # Общая статистика по задачам
        result = await session.execute(
            select(ParseTask.status, func.count(ParseTask.id)).group_by(ParseTask.status)
        )
        counts = dict(result.all())

    total = sum(counts.values())
    done = counts.get(TaskStatus.done.value, 0)
    not_found = counts.get(TaskStatus.not_found.value, 0)
    failed = counts.get(TaskStatus.failed.value, 0)
    in_progress = counts.get(TaskStatus.in_progress.value, 0)
    pending = counts.get(TaskStatus.pending.value, 0) + counts.get(
        TaskStatus.resume_pending.value, 0
    )

    return {
        "running": _parsing_state["running"],
        "total": total,
        "done": done,
        "not_found": not_found,
        "failed": failed,
        "in_progress": in_progress,
        "pending": pending,
    }


@app.get("/api/results")
async def get_results():
    async with async_session() as session:
        # Получаем результаты: ИНН + номер дела из fedresurs,
        # название и ссылка документа из kad_arbitr
        fed_rows = await session.execute(
            select(
                FedresursResult.inn,
                FedresursResult.case_number,
            ).order_by(FedresursResult.id)
        )
        fed_data = fed_rows.all()

        kad_rows = await session.execute(
            select(
                KadArbitrResult.case_number,
                KadArbitrResult.document_name,
                KadArbitrResult.document_title,
            ).order_by(KadArbitrResult.id)
        )
        kad_map: dict[str, dict] = {}
        for row in kad_rows.all():
            kad_map[row.case_number] = {
                "document_name": row.document_name,
                "document_url": row.document_title,
            }

    results = []
    for row in fed_data:
        kad = kad_map.get(row.case_number, {})
        results.append({
            "inn": row.inn,
            "case_number": row.case_number,
            "document_name": kad.get("document_name", ""),
            "document_url": kad.get("document_url", ""),
        })

    return {"results": results}


@app.get("/api/results/download")
async def download_results():
    import openpyxl

    async with async_session() as session:
        fed_rows = await session.execute(
            select(
                FedresursResult.inn,
                FedresursResult.case_number,
            ).order_by(FedresursResult.id)
        )
        fed_data = fed_rows.all()

        kad_rows = await session.execute(
            select(
                KadArbitrResult.case_number,
                KadArbitrResult.document_name,
                KadArbitrResult.document_title,
            ).order_by(KadArbitrResult.id)
        )
        kad_map: dict[str, dict] = {}
        for row in kad_rows.all():
            kad_map[row.case_number] = {
                "document_name": row.document_name,
                "document_url": row.document_title,
            }

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Results"
    ws.append(["ИНН", "Номер дела", "Название документа", "Ссылка на документ"])

    for row in fed_data:
        kad = kad_map.get(row.case_number, {})
        ws.append([
            row.inn,
            row.case_number,
            kad.get("document_name", ""),
            kad.get("document_url", ""),
        ])

    output_dir = BASE_DIR / "output"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "results.xlsx"
    wb.save(str(output_path))

    return FileResponse(
        str(output_path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="results.xlsx",
    )


def _on_parsing_done(task: asyncio.Task) -> None:
    _parsing_state["running"] = False
    _parsing_state["task"] = None
    _parsing_state["stop_event"] = None
    exc = task.exception() if not task.cancelled() else None
    if exc:
        logger.error("Parsing task failed: %s", exc)


async def _run_parsing(stop_event: asyncio.Event, resume: bool = False) -> None:
    """Запускает полный цикл парсинга (импорт + recovery + воркеры)."""
    from sqlalchemy import text

    from src.services.excel_reader import read_identifiers
    from src.services.task_service import import_tasks, recover_stale_tasks

    logger.info("Parsing started (resume=%s)", resume)

    # Проверяем БД
    async with async_session() as session:
        await session.execute(text("SELECT 1"))

    # Импорт задач (если не resume — полный импорт)
    if not resume:
        read_result = read_identifiers()
        async with async_session() as session:
            await import_tasks(session, read_result.valid)

    # Recovery
    async with async_session() as session:
        await recover_stale_tasks(session)

    # Запуск воркеров с поддержкой stop_event
    await _run_workers_with_stop(stop_event)

    logger.info("Parsing finished")


async def _run_workers_with_stop(stop_event: asyncio.Event) -> None:
    """Запускает воркеры с возможностью остановки через stop_event."""
    from src.browser.factory import BrowserFactory
    from src.services.worker_runner import run_stage_worker

    stage1_done = asyncio.Event()

    async def stage1():
        async with BrowserFactory(cdp_port=settings.cdp_port) as factory:
            logger.info("Stage1 (fedresurs) browser ready")
            await run_stage_worker(
                factory,
                task_type="fedresurs",
                worker_name="stage1_fedresurs",
                stop_event=stop_event,
            )
        stage1_done.set()

    async def stage2():
        await asyncio.sleep(3)
        async with BrowserFactory(cdp_port=settings.cdp_port_stage2) as factory:
            logger.info("Stage2 (kad_arbitr) browser ready")
            await run_stage_worker(
                factory,
                task_type="kad_arbitr",
                worker_name="stage2_kad_arbitr",
                stop_event=stage1_done,
                poll=True,
            )

    # Если stop_event установлен — не запускаем
    if stop_event.is_set():
        return

    tasks = [asyncio.create_task(stage1()), asyncio.create_task(stage2())]

    # Ждём либо завершения, либо stop_event
    stop_waiter = asyncio.create_task(stop_event.wait())
    done, pending = await asyncio.wait(
        [*tasks, stop_waiter], return_when=asyncio.FIRST_COMPLETED,
    )

    if stop_event.is_set():
        logger.info("Stop requested, cancelling workers...")
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    else:
        # stop_waiter не завершился, отменяем его
        stop_waiter.cancel()
        # Ждём оставшиеся задачи
        for t in pending:
            if t is not stop_waiter:
                await t
