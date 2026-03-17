import asyncio
import sys

from sqlalchemy import text

from src.core.config import settings
from src.core.logger import get_logger, setup_logger
from src.db.session import async_session

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def check_db() -> None:
    logger = get_logger(__name__)
    logger.info("Checking database connection...")
    async with async_session() as session:
        await session.execute(text("SELECT 1"))
    logger.info("Database connection successful")


async def run_import() -> None:
    from src.services.excel_reader import read_identifiers
    from src.services.task_service import import_tasks

    read_result = read_identifiers()
    async with async_session() as session:
        import_result = await import_tasks(session, read_result.valid)
    logger = get_logger(__name__)
    logger.info(
        "Tasks in DB: created=%d, skipped=%d",
        import_result.created,
        import_result.skipped,
    )


async def run_recovery() -> None:
    from src.services.task_service import recover_stale_tasks

    logger = get_logger(__name__)
    async with async_session() as session:
        recovered = await recover_stale_tasks(session)
    if recovered:
        logger.info("Recovery: recovered=%d stale task(s)", recovered)
    else:
        logger.info("Recovery: no stale tasks")


async def run_next_task() -> None:
    from src.services.worker_service import run_worker

    async with async_session() as session:
        await run_worker(session)


async def startup() -> None:
    await check_db()
    await run_import()
    await run_recovery()
    await run_next_task()


def main() -> None:
    setup_logger()
    logger = get_logger(__name__)

    logger.info("Application started")
    logger.info("App name: %s", settings.app_name)
    logger.info("Environment: %s", settings.app_env)
    logger.info("Headless: %s", settings.playwright_headless)

    asyncio.run(startup())


if __name__ == "__main__":
    main()
