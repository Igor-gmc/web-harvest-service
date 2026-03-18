from sqlalchemy.ext.asyncio import AsyncSession

from src.browser.factory import BrowserFactory
from src.core.config import settings
from src.core.logger import get_logger
from src.db.repositories import acquire_next_task
from src.db.session import async_session
from src.services.task_executor import execute_task
from src.services.task_service import fail_task

logger = get_logger(__name__)


async def run_batch(factory: BrowserFactory, worker_name: str = "direct_worker") -> int:
    """Batch worker: обрабатывает все доступные задачи и завершается.

    Переиспользует вкладку браузера между задачами:
    - После успеха: page на главной (клик по логотипу)
    - После «Ничего не найдено»: page на странице результатов
    - После ошибки: page закрыт executor'ом, берём новую

    Возвращает количество обработанных задач.
    """
    processed = 0
    reuse_page = None
    on_results = False

    while True:
        async with async_session() as session:
            task = await acquire_next_task(session, worker_name, settings.lock_ttl_seconds)
            if task is None:
                break

            logger.info(
                "Task acquired: id=%d, type=%s, source_value=%s",
                task.id, task.task_type, task.source_value,
            )

            try:
                reuse_page, on_results = await execute_task(
                    session, task, factory,
                    reuse_page=reuse_page,
                    reuse_on_results=on_results,
                )
            except Exception as exc:
                logger.error(
                    "Unexpected error in worker loop: task_id=%d, error=%s", task.id, exc,
                )
                await _safe_fail(session, task, exc)
                reuse_page = None
                on_results = False

            processed += 1

    if reuse_page is not None:
        await factory.release_page(reuse_page)

    logger.info("Batch complete: processed=%d", processed)
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
