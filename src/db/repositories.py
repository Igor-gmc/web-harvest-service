from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.enums import CheckpointStep, TaskStatus
from src.db.models import FedresursResult, ParseTask, TaskEvent
from src.schemas.results import FedresursResultData


async def task_exists(session: AsyncSession, task_type: str, source_value: str) -> bool:
    """Проверяет, существует ли задача с таким task_type и source_value."""
    result = await session.execute(
        select(ParseTask.id).where(
            ParseTask.task_type == task_type,
            ParseTask.source_value == source_value,
        )
    )
    return result.scalar_one_or_none() is not None


async def create_task(
    session: AsyncSession, task_type: str, source_value: str
) -> ParseTask:
    """Создаёт задачу в сессии (без commit — коммитит вызывающий код)."""
    task = ParseTask(
        task_type=task_type,
        source_value=source_value,
        status=TaskStatus.pending,
        checkpoint_step=CheckpointStep.init,
        attempt_count=0,
    )
    session.add(task)
    return task


async def get_stale_tasks(session: AsyncSession) -> list[ParseTask]:
    """Возвращает in_progress задачи с истёкшим lock_expires_at."""
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(ParseTask).where(
            ParseTask.status == TaskStatus.in_progress,
            ParseTask.lock_expires_at < now,
        )
    )
    return list(result.scalars().all())


async def acquire_next_task(
    session: AsyncSession, worker_name: str, lock_ttl_seconds: int
) -> ParseTask | None:
    """Выбирает следующую задачу (resume_pending приоритетнее pending) и переводит её в in_progress.

    Заполняет worker_name, locked_by, started_at, last_heartbeat_at, lock_expires_at.
    Commit выполняется здесь — захват атомарен.
    Возвращает задачу или None если очередь пуста.
    """
    task: ParseTask | None = None
    for status in (TaskStatus.resume_pending, TaskStatus.pending):
        result = await session.execute(
            select(ParseTask)
            .where(ParseTask.status == status)
            .order_by(ParseTask.id)
            .limit(1)
        )
        task = result.scalar_one_or_none()
        if task is not None:
            break

    if task is None:
        return None

    now = datetime.now(timezone.utc)
    task.status = TaskStatus.in_progress
    task.worker_name = worker_name
    task.locked_by = worker_name
    task.started_at = now
    task.last_heartbeat_at = now
    task.lock_expires_at = now + timedelta(seconds=lock_ttl_seconds)

    await session.commit()
    return task


async def refresh_heartbeat(
    session: AsyncSession, task: ParseTask, lock_ttl_seconds: int
) -> None:
    """Обновляет last_heartbeat_at и продлевает lock_expires_at. Commit здесь."""
    now = datetime.now(timezone.utc)
    task.last_heartbeat_at = now
    task.lock_expires_at = now + timedelta(seconds=lock_ttl_seconds)
    await session.commit()


async def save_fedresurs_result(
    session: AsyncSession, data: FedresursResultData
) -> FedresursResult:
    """Сохраняет результат парсинга fedresurs (без commit — коммитит вызывающий код)."""
    record = FedresursResult(
        task_id=data.task_id,
        inn=data.inn,
        case_number=data.case_number,
        last_publication_date=data.last_publication_date,
        parsed_at=data.parsed_at,
    )
    session.add(record)
    return record


async def create_task_event(
    session: AsyncSession,
    task_id: int,
    event_type: str,
    message: str | None = None,
) -> TaskEvent:
    """Добавляет событие в историю задачи (без commit — коммитит вызывающий код)."""
    event = TaskEvent(task_id=task_id, event_type=event_type, message=message)
    session.add(event)
    return event
