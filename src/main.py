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


async def startup() -> None:
    await check_db()
    await run_import()


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
