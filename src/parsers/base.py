from abc import ABC, abstractmethod

from src.db.models import ParseTask
from src.schemas.results import FedresursResultData


class BaseParser(ABC):
    """Базовый интерфейс парсера.

    Парсер отвечает только за получение предметных данных.
    Он ничего не знает про heartbeat, lifecycle задачи и работу с БД.
    """

    @abstractmethod
    async def parse(self, task: ParseTask) -> list[FedresursResultData]:
        """Выполняет парсинг и возвращает список результатов.

        Не делает commit и не обновляет статус задачи.
        """
        ...
