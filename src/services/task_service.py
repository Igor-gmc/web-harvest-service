from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.enums import CheckpointStep, ErrorType, TaskStatus, TaskType
from src.core.logger import get_logger
from src.db.models import ParseTask
from src.db.repositories import (
    create_task,
    create_task_event,
    delete_all_tasks_by_type,
    delete_task_results,
    get_all_source_values,
    get_case_numbers_for_kad_import,
    get_stale_tasks,
    get_task,
)
from src.schemas.input import InputRow

logger = get_logger(__name__)


_RESET_STATUSES = {TaskStatus.failed}


@dataclass
class ImportResult:
    created: int
    reset: int
    skipped: int


async def _reset_task(session: AsyncSession, task: ParseTask) -> None:
    """Сбрасывает завершённую задачу обратно в pending для повторного парсинга.

    Удаляет старые результаты чтобы не было конфликтов UniqueConstraint.
    """
    await delete_task_results(session, task)
    task.status = TaskStatus.pending
    task.checkpoint_step = CheckpointStep.init
    task.checkpoint_data = None
    task.last_error = None
    task.last_error_type = None
    task.finished_at = None
    task.started_at = None
    task.locked_by = None
    task.lock_expires_at = None
    task.worker_name = None


async def import_tasks(session: AsyncSession, rows: list[InputRow]) -> ImportResult:
    """Импортирует fedresurs-задачи в parse_tasks для каждого валидного ИНН.

    Сравнивает список ИНН из файла с БД:
    - Если список изменился (добавлены/удалены/изменены ИНН) — полный сброс:
      удаляет все fedresurs и kad_arbitr задачи, создаёт заново из файла.
    - Если список не изменился — только failed задачи сбрасываются для повторной попытки.
    """
    file_inns = {row.inn for row in rows}
    db_inns = await get_all_source_values(session, TaskType.fedresurs.value)

    # Файл изменился — полный сброс обоих типов задач
    if file_inns != db_inns:
        deleted_fed = await delete_all_tasks_by_type(session, TaskType.fedresurs.value)
        deleted_kad = await delete_all_tasks_by_type(session, TaskType.kad_arbitr.value)
        logger.info(
            "File changed: deleted %d fedresurs + %d kad_arbitr tasks",
            deleted_fed, deleted_kad,
        )

        for row in rows:
            await create_task(session, TaskType.fedresurs.value, row.inn)

        await session.commit()
        logger.info("Import complete: created=%d (full reset)", len(rows))
        return ImportResult(created=len(rows), reset=0, skipped=0)

    # Файл не изменился — только retry failed
    created = 0
    reset = 0
    skipped = 0

    for row in rows:
        existing = await get_task(session, TaskType.fedresurs.value, row.inn)
        if existing:
            if existing.status in _RESET_STATUSES:
                await _reset_task(session, existing)
                logger.debug("Reset failed: %s / %s", TaskType.fedresurs.value, row.inn)
                reset += 1
            else:
                skipped += 1
        else:
            await create_task(session, TaskType.fedresurs.value, row.inn)
            created += 1

    await session.commit()
    logger.info("Import complete: created=%d, reset=%d, skipped=%d", created, reset, skipped)
    return ImportResult(created=created, reset=reset, skipped=skipped)


async def import_kad_arbitr_tasks(session: AsyncSession) -> ImportResult:
    """Импортирует kad_arbitr-задачи из fedresurs_results.case_number.

    Берёт уникальные номера дел из завершённых fedresurs-задач.
    Завершённые задачи сбрасываются в pending для повторного парсинга.
    """
    case_numbers = await get_case_numbers_for_kad_import(session)
    created = 0
    reset = 0
    skipped = 0

    for cn in case_numbers:
        existing = await get_task(session, TaskType.kad_arbitr.value, cn)
        if existing:
            if existing.status in _RESET_STATUSES:
                await _reset_task(session, existing)
                logger.debug("Reset: %s / %s", TaskType.kad_arbitr.value, cn)
                reset += 1
            else:
                logger.debug("Skip in-progress: %s / %s", TaskType.kad_arbitr.value, cn)
                skipped += 1
        else:
            await create_task(session, TaskType.kad_arbitr.value, cn)
            logger.debug("Queue: %s / %s", TaskType.kad_arbitr.value, cn)
            created += 1

    await session.commit()
    logger.info("Import kad_arbitr complete: created=%d, reset=%d, skipped=%d", created, reset, skipped)
    return ImportResult(created=created, reset=reset, skipped=skipped)


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


async def update_checkpoint(
    session: AsyncSession,
    task: ParseTask,
    step: CheckpointStep,
    data: dict | None = None,
) -> None:
    """Обновляет checkpoint задачи и записывает событие."""
    task.checkpoint_step = step.value
    if data is not None:
        task.checkpoint_data = {**(task.checkpoint_data or {}), **data}
    await create_task_event(session, task.id, f"checkpoint_{step.value}")
    await session.commit()


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
