from dataclasses import dataclass, field
from enum import Enum


class InnType(str, Enum):
    """Тип субъекта по длине ИНН."""

    legal = "legal"         # юридическое лицо / ООО — 10 цифр
    individual = "individual"  # физическое лицо / ИП  — 12 цифр


@dataclass(frozen=True)
class InputRow:
    """Одна валидная и нормализованная строка входного Excel-файла."""

    inn: str       # только цифры, длина 10 или 12
    inn_type: InnType


@dataclass
class ExcelReadResult:
    """Итог чтения Excel: валидные строки + статистика пропусков."""

    valid: list[InputRow] = field(default_factory=list)
    total_rows: int = 0
    skipped_invalid: int = 0
    skipped_duplicate: int = 0

    @property
    def valid_count(self) -> int:
        return len(self.valid)
