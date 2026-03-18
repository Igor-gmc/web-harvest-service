from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.enums import CheckpointStep, ErrorType, TaskStatus, TaskType
from src.core.logger import get_logger
from src.db.models import ParseTask
from src.db.repositories import create_task, create_task_event, get_stale_tasks, task_exists
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


async def recover_stale_tasks(session: AsyncSession) -> int:
    """Находит зависшие in_progress задачи (просроченный lock) и возвращает их в resume_pending.

    Очищает lock-поля и worker_name. Пишет событие task_recovered для каждой.
    Один commit в конце.
    Возвращает количество восстановленных задач.
    """
    stale = await get_stale_tasks(session)
    if not stale:
        return 0

    for task in stale:
        task.status = TaskStatus.resume_pending
        task.locked_by = None
        task.lock_expires_at = None
        task.worker_name = None
        await create_task_event(
            session,
            task.id,
            "task_recovered",
            "Task recovered after lock expiry",
        )
        logger.info(
            "Recovered stale task: id=%d, source_value=%s", task.id, task.source_value
        )

    await session.commit()
    logger.info("Recovery complete: recovered=%d", len(stale))
    return len(stale)


async def complete_task(
    session: AsyncSession,
    task: ParseTask,
    message: str = "Stub processing completed successfully",
) -> None:
    """Переводит задачу в done, снимает блокировку, пишет событие."""
    now = datetime.now(timezone.utc)
    task.status = TaskStatus.done
    task.checkpoint_step = CheckpointStep.done
    task.finished_at = now
    task.locked_by = None
    task.lock_expires_at = None

    await create_task_event(session, task.id, "task_completed", message)
    await session.commit()
    logger.info("Task done: id=%d, source_value=%s", task.id, task.source_value)


async def not_found_task(
    session: AsyncSession,
    task: ParseTask,
    message: str = "No results found for this INN",
) -> None:
    """Переводит задачу в not_found — ИНН обработан, но данных нет."""
    now = datetime.now(timezone.utc)
    task.status = TaskStatus.not_found
    task.checkpoint_step = CheckpointStep.done
    task.finished_at = now
    task.locked_by = None
    task.lock_expires_at = None

    await create_task_event(session, task.id, "task_not_found", message)
    await session.commit()
    logger.info("Task not_found: id=%d, source_value=%s", task.id, task.source_value)


async def fail_task(
    session: AsyncSession,
    task: ParseTask,
    error_message: str,
    error_type: ErrorType = ErrorType.unknown,
) -> None:
    """Переводит задачу в failed, снимает блокировку, пишет событие."""
    now = datetime.now(timezone.utc)
    task.status = TaskStatus.failed
    task.finished_at = now
    task.locked_by = None
    task.lock_expires_at = None
    task.last_error = error_message
    task.last_error_type = error_type.value

    await create_task_event(session, task.id, "task_failed", error_message)
    await session.commit()
    logger.info(
        "Task failed: id=%d, source_value=%s, error=%s",
        task.id,
        task.source_value,
        error_message,
    )
