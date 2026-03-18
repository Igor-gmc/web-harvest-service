import asyncio

from sqlalchemy import text

from src.core.config import settings
from src.core.logger import get_logger, setup_logger
from src.db.session import async_session


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
        "Tasks in DB: created=%d, reset=%d, skipped=%d",
        import_result.created,
        import_result.reset,
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


async def run_parallel_workers() -> None:
    from src.browser.factory import BrowserFactory
    from src.services.worker_runner import run_stage_worker

    logger = get_logger(__name__)

    # Stage1 завершается когда очередь fedresurs пуста.
    # Stage2 поллит БД, пока stage1 работает, потом дорабатывает остаток и завершается.
    stage1_done = asyncio.Event()

    async def stage1():
        async with BrowserFactory(cdp_port=settings.cdp_port) as factory:
            logger.info("Stage1 (fedresurs) browser ready, port=%d", settings.cdp_port)
            processed = await run_stage_worker(
                factory,
                task_type="fedresurs",
                worker_name="stage1_fedresurs",
            )
        logger.info("Stage1 (fedresurs) finished: processed=%d", processed)
        stage1_done.set()

    async def stage2():
        # Даём stage1 немного времени начать работу
        await asyncio.sleep(3)
        async with BrowserFactory(cdp_port=settings.cdp_port_stage2) as factory:
            logger.info("Stage2 (kad_arbitr) browser ready, port=%d", settings.cdp_port_stage2)
            processed = await run_stage_worker(
                factory,
                task_type="kad_arbitr",
                worker_name="stage2_kad_arbitr",
                stop_event=stage1_done,
                poll=True,
            )
        logger.info("Stage2 (kad_arbitr) finished: processed=%d", processed)

    await asyncio.gather(stage1(), stage2())


async def startup() -> None:
    await check_db()
    await run_import()
    await run_recovery()
    await run_parallel_workers()


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
