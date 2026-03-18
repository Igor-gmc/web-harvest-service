from sqlalchemy.ext.asyncio import AsyncSession

from src.browser.factory import BrowserFactory
from src.core.config import settings
from src.core.logger import get_logger
from src.db.repositories import acquire_next_task
from src.services.task_executor import execute_task

logger = get_logger(__name__)

WORKER_NAME = "direct_worker"


async def run_worker(session: AsyncSession, factory: BrowserFactory) -> bool:
    """Берёт следующую задачу и передаёт её executor'у.

    Возвращает True если задача была обработана, False если очередь пуста.
    """
    task = await acquire_next_task(session, WORKER_NAME, settings.lock_ttl_seconds)
    if task is None:
        logger.info("No pending tasks — queue is empty")
        return False

    logger.info(
        "Task acquired: id=%d, type=%s, source_value=%s",
        task.id,
        task.task_type,
        task.source_value,
    )

    await execute_task(session, task, factory)
    return True
