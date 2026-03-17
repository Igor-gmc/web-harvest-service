from datetime import datetime, timezone

from src.core.logger import get_logger
from src.db.models import ParseTask
from src.parsers.base import BaseParser
from src.schemas.results import FedresursResultData

logger = get_logger(__name__)


class FedresursParser(BaseParser):
    """Stub-парсер fedresurs.ru.

    Сейчас возвращает заглушечные данные.
    В будущем здесь будет Playwright.
    """

    async def parse(self, task: ParseTask) -> list[FedresursResultData]:
        logger.info("FedresursParser started: task_id=%d, inn=%s", task.id, task.source_value)

        # Stub: в будущем здесь Playwright откроет fedresurs.ru и соберёт реальные данные
        now = datetime.now(timezone.utc)
        results = [
            FedresursResultData(
                task_id=task.id,
                inn=task.source_value,
                case_number=f"STUB-{task.id:04d}",
                parsed_at=now,
                last_publication_date=None,
            )
        ]

        logger.info(
            "FedresursParser finished: task_id=%d, results=%d", task.id, len(results)
        )
        return results
