from dataclasses import dataclass
from datetime import datetime


@dataclass
class FedresursResultData:
    """Данные одной записи fedresurs для сохранения в БД."""

    task_id: int
    inn: str
    case_number: str
    parsed_at: datetime
    last_publication_date: datetime | None = None
