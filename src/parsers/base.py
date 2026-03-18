from abc import ABC, abstractmethod
from typing import Awaitable, Callable

from src.browser.factory import BrowserFactory
from src.db.models import ParseTask

CheckpointFn = Callable[..., Awaitable[None]]


class BaseParser(ABC):
    """Базовый интерфейс парсера.

    Парсер отвечает только за получение предметных данных.
    Он ничего не знает про heartbeat, lifecycle задачи и работу с БД.
    """

    @abstractmethod
    async def parse(self, task: ParseTask, factory: BrowserFactory) -> list:
        """Выполняет парсинг и возвращает список результатов."""
        ...
