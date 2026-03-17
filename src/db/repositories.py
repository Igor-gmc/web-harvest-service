from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.enums import CheckpointStep, TaskStatus
from src.db.models import ParseTask


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
