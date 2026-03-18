import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from src.browser.factory import BrowserFactory
from src.core.config import settings
from src.core.logger import get_logger
from src.db.repositories import acquire_next_task
from src.db.session import async_session
from src.services.task_executor import execute_task
from src.services.task_service import fail_task

logger = get_logger(__name__)

POLL_INTERVAL_SECONDS = 5


async def run_stage_worker(
    factory: BrowserFactory,
    task_type: str,
    worker_name: str = "worker",
    stop_event: asyncio.Event | None = None,
    poll: bool = False,
) -> int:
    """Воркер одного этапа: обрабатывает задачи указанного task_type.

    Переиспользует вкладку браузера между задачами.

    Args:
        factory: BrowserFactory для этого воркера (свой CDP порт).
        task_type: "fedresurs" или "kad_arbitr".
        worker_name: Имя воркера для логов и lock.
        stop_event: Если установлен — воркер завершается даже если poll=True.
        poll: Если True — при пустой очереди ждёт новых задач (для stage2).
              Если False — завершается при пустой очереди (для stage1).

    Returns:
        Количество обработанных задач.
    """
    processed = 0
    reuse_page = None
    on_results = False

    while True:
        # Проверяем stop_event перед взятием новой задачи
        if stop_event is not None and stop_event.is_set() and not poll:
            logger.info("[%s] Stop requested, finishing...", worker_name)
            break

        async with async_session() as session:
            task = await acquire_next_task(
                session, worker_name, settings.lock_ttl_seconds, task_type=task_type,
            )

            if task is None:
                # poll=True: ждём новых задач, пока stage1 ещё работает
                if poll and (stop_event is None or not stop_event.is_set()):
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
                    continue
                # stage1 завершён (stop_event set) и очередь пуста → выходим
                break

            logger.info(
                "[%s] Task acquired: id=%d, source=%s",
                worker_name, task.id, task.source_value,
            )

            try:
                reuse_page, on_results = await execute_task(
                    session, task, factory,
                    reuse_page=reuse_page,
                    reuse_on_results=on_results,
                )
            except Exception as exc:
                logger.error(
                    "[%s] Unexpected error: task_id=%d, error=%s", worker_name, task.id, exc,
                )
                await _safe_fail(session, task, exc)
                reuse_page = None
                on_results = False

            processed += 1

    if reuse_page is not None:
        await factory.release_page(reuse_page)

    logger.info("[%s] Worker finished: processed=%d", worker_name, processed)
    return processed


async def _safe_fail(session: AsyncSession, task, exc: Exception) -> None:
    """Переводит задачу в failed, если executor этого не сделал."""
    try:
        from src.core.enums import TaskStatus
        await session.refresh(task)
        if task.status not in (TaskStatus.done, TaskStatus.not_found, TaskStatus.failed):
            await fail_task(session, task, f"WorkerLoop: {type(exc).__name__}: {exc}")
    except Exception as inner:
        logger.error("Failed to mark task as failed: task_id=%d, error=%s", task.id, inner)
