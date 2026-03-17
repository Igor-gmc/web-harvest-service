import logging
import sys
from pathlib import Path

from src.core.config import BASE_DIR, settings

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "app.log"


def setup_logger() -> None:
    """Настраивает корневой логгер: stdout + файл."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    # Очищаем старые handlers (при повторном вызове)
    root.handlers.clear()

    formatter = logging.Formatter(LOG_FORMAT)

    # Консоль
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

    # Файл
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Возвращает именованный логгер."""
    return logging.getLogger(name)
