import asyncio

from playwright.async_api import Page
from sqlalchemy.ext.asyncio import AsyncSession

from src.browser.factory import BrowserFactory
from src.core.config import settings
from src.core.logger import get_logger
from src.db.models import ParseTask
from src.db.repositories import refresh_heartbeat, save_fedresurs_result
from src.services.task_service import complete_task, fail_task, not_found_task

logger = get_logger(__name__)

HEARTBEAT_STEPS = 3
HEARTBEAT_STEP_SECONDS = 1


async def execute_task(
    session: AsyncSession,
    task: ParseTask,
    factory: BrowserFactory,
    reuse_page: Page | None = None,
    reuse_on_results: bool = False,
) -> tuple[Page | None, bool]:
    """Выполняет задачу: выбирает парсер, держит heartbeat, сохраняет результаты, завершает.

    Возвращает (page, on_results_page):
    - (page, True)  — «Ничего не найдено», page на странице результатов
    - (page, False) — Успех, page на главной странице (после клика по логотипу)
    - (None, False) — Ошибка или NoBankruptcyData, вкладка закрыта
    """
    logger.info("TaskExecutor started: id=%d, type=%s", task.id, task.task_type)

    if task.task_type == "fedresurs":
        from src.parsers.fedresurs import FedresursParser
        parser = FedresursParser()
    else:
        await fail_task(session, task, f"Unknown task_type: {task.task_type}")
        logger.error("TaskExecutor: unknown task_type=%s, id=%d", task.task_type, task.id)
        if reuse_page is not None:
            await factory.release_page(reuse_page)
        return None, False

    # Heartbeat во время парсинга — показывает, что воркер жив
    async def heartbeat_loop() -> None:
        for step in range(1, HEARTBEAT_STEPS + 1):
            await asyncio.sleep(HEARTBEAT_STEP_SECONDS)
            await refresh_heartbeat(session, task, settings.lock_ttl_seconds)
            logger.info(
                "Task heartbeat refreshed: id=%d, step=%d/%d", task.id, step, HEARTBEAT_STEPS
            )

    await heartbeat_loop()

    try:
        results = await parser.parse(
            task, factory,
            reuse_page=reuse_page,
            reuse_on_results=reuse_on_results,
        )
    except Exception as exc:
        from src.parsers.fedresurs import NoBankruptcyDataError, NoResultsFoundError

        if isinstance(exc, NoResultsFoundError):
            await not_found_task(session, task, str(exc))
            return exc.page, True

        if isinstance(exc, NoBankruptcyDataError):
            await not_found_task(session, task, str(exc))
            return None, False

        await fail_task(session, task, f"{type(exc).__name__}: {exc}")
        logger.error("TaskExecutor failed: id=%d, error=%s", task.id, exc)
        return None, False

    for result in results:
        await save_fedresurs_result(session, result)

    logger.info("TaskExecutor finished: id=%d, results_saved=%d", task.id, len(results))
    await complete_task(session, task)
    # Вкладка на главной странице — переиспользуем
    return parser.reuse_page, False
