from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.enums import CheckpointStep, TaskStatus
from src.db.models import FedresursResult, KadArbitrResult, ParseTask, TaskEvent
from src.schemas.kad_result import KadArbitrResultData
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


async def get_task(
    session: AsyncSession, task_type: str, source_value: str
) -> ParseTask | None:
    """Возвращает задачу по task_type и source_value или None."""
    result = await session.execute(
        select(ParseTask).where(
            ParseTask.task_type == task_type,
            ParseTask.source_value == source_value,
        )
    )
    return result.scalar_one_or_none()


async def delete_task_results(session: AsyncSession, task: ParseTask) -> None:
    """Удаляет результаты и события задачи (для повторного парсинга)."""
    await session.execute(
        delete(FedresursResult).where(FedresursResult.task_id == task.id)
    )
    await session.execute(
        delete(KadArbitrResult).where(KadArbitrResult.task_id == task.id)
    )
    await session.execute(
        delete(TaskEvent).where(TaskEvent.task_id == task.id)
    )


async def get_all_source_values(session: AsyncSession, task_type: str) -> set[str]:
    """Возвращает множество source_value для данного task_type."""
    result = await session.execute(
        select(ParseTask.source_value).where(ParseTask.task_type == task_type)
    )
    return set(result.scalars().all())


async def delete_all_tasks_by_type(session: AsyncSession, task_type: str) -> int:
    """Удаляет все задачи данного типа вместе с результатами и событиями.

    Каскадное удаление через FK (ondelete=CASCADE) уберёт results и events.
    Возвращает количество удалённых задач.
    """
    result = await session.execute(
        select(ParseTask.id).where(ParseTask.task_type == task_type)
    )
    task_ids = list(result.scalars().all())
    if not task_ids:
        return 0

    # Удаляем результаты и события (CASCADE может не сработать через ORM delete)
    for model in (FedresursResult, KadArbitrResult, TaskEvent):
        await session.execute(
            delete(model).where(model.task_id.in_(task_ids))
        )
    await session.execute(
        delete(ParseTask).where(ParseTask.task_type == task_type)
    )
    return len(task_ids)


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


async def save_kad_arbitr_result(
    session: AsyncSession, data: KadArbitrResultData
) -> KadArbitrResult:
    """Сохраняет результат парсинга kad.arbitr (без commit — коммитит вызывающий код)."""
    record = KadArbitrResult(
        task_id=data.task_id,
        case_number=data.case_number,
        document_date=data.document_date,
        document_title=data.document_title,
        document_name=data.document_name,
        parsed_at=data.parsed_at,
    )
    session.add(record)
    return record


async def get_case_numbers_for_kad_import(session: AsyncSession) -> list[str]:
    """Возвращает уникальные case_number из fedresurs_results (done задачи)."""
    result = await session.execute(
        select(FedresursResult.case_number)
        .join(ParseTask)
        .where(ParseTask.status == TaskStatus.done.value)
        .distinct()
    )
    return list(result.scalars().all())


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
