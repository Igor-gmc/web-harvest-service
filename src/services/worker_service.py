from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.logger import get_logger
from src.db.repositories import acquire_next_task
from src.services.task_executor import execute_task

logger = get_logger(__name__)

WORKER_NAME = "direct_worker"


async def run_worker(session: AsyncSession) -> None:
    """Берёт следующую задачу и передаёт её executor'у."""
    task = await acquire_next_task(session, WORKER_NAME, settings.lock_ttl_seconds)
    if task is None:
        logger.info("No pending tasks — queue is empty")
        return

    logger.info(
        "Task acquired: id=%d, type=%s, source_value=%s",
        task.id,
        task.task_type,
        task.source_value,
    )

    await execute_task(session, task)
