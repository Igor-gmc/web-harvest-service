from dataclasses import dataclass
from datetime import datetime


@dataclass
class KadArbitrResultData:
    """Данные одной записи kad.arbitr для сохранения в БД."""

    task_id: int
    case_number: str
    parsed_at: datetime
    document_date: datetime | None = None
    document_title: str | None = None
    document_name: str | None = None
