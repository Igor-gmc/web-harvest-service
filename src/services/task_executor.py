import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.logger import get_logger
from src.db.models import ParseTask
from src.db.repositories import refresh_heartbeat, save_fedresurs_result
from src.services.task_service import complete_task, fail_task

logger = get_logger(__name__)

HEARTBEAT_STEPS = 3
HEARTBEAT_STEP_SECONDS = 5


async def execute_task(session: AsyncSession, task: ParseTask) -> None:
    """Выполняет задачу: выбирает парсер, держит heartbeat, сохраняет результаты, завершает.

    Executor отвечает за lifecycle исполнения.
    Парсер отвечает только за получение данных.
    """
    logger.info("TaskExecutor started: id=%d, type=%s", task.id, task.task_type)

    if task.task_type == "fedresurs":
        from src.parsers.fedresurs import FedresursParser
        parser = FedresursParser()
    else:
        await fail_task(session, task, f"Unknown task_type: {task.task_type}")
        logger.error("TaskExecutor: unknown task_type=%s, id=%d", task.task_type, task.id)
        return

    # Heartbeat во время парсинга — показывает, что воркер жив
    async def heartbeat_loop() -> None:
        for step in range(1, HEARTBEAT_STEPS + 1):
            await asyncio.sleep(HEARTBEAT_STEP_SECONDS)
            await refresh_heartbeat(session, task, settings.lock_ttl_seconds)
            logger.info(
                "Task heartbeat refreshed: id=%d, step=%d/%d", task.id, step, HEARTBEAT_STEPS
            )

    await heartbeat_loop()

    results = await parser.parse(task)

    for result in results:
        await save_fedresurs_result(session, result)

    logger.info("TaskExecutor finished: id=%d, results_saved=%d", task.id, len(results))
    await complete_task(session, task)
