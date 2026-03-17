from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.enums import TaskType
from src.core.logger import get_logger
from src.db.repositories import create_task, task_exists
from src.schemas.input import InputRow

logger = get_logger(__name__)


@dataclass
class ImportResult:
    created: int
    skipped: int


async def import_tasks(session: AsyncSession, rows: list[InputRow]) -> ImportResult:
    """Импортирует fedresurs-задачи в parse_tasks для каждого валидного ИНН.

    Уже существующие задачи пропускаются без ошибки.
    Commit выполняется один раз в конце для эффективности.
    """
    created = 0
    skipped = 0

    for row in rows:
        if await task_exists(session, TaskType.fedresurs.value, row.inn):
            logger.debug("Skip existing: %s / %s", TaskType.fedresurs.value, row.inn)
            skipped += 1
        else:
            await create_task(session, TaskType.fedresurs.value, row.inn)
            logger.debug("Queue: %s / %s", TaskType.fedresurs.value, row.inn)
            created += 1

    await session.commit()
    logger.info("Import complete: created=%d, skipped=%d", created, skipped)
    return ImportResult(created=created, skipped=skipped)
