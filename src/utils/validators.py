import re

from src.schemas.input import InnType


def normalize_inn(raw: object) -> str | None:
    """Нормализует значение ячейки Excel в строку ИНН.

    Обрабатывает форматы:
      - целое число:        231138771115
      - число с пробелами:  "231 138 771 115"
      - с дефисами:         "231-138-771-115"
      - с префиксом:        "ИНН 231138771118"
      - невалидные:         None, отрицательные числа, пустые строки
    """
    if raw is None:
        return None

    # Отрицательное число — явно битые данные
    if isinstance(raw, (int, float)) and raw < 0:
        return None

    # float без дробной части → int (Excel иногда хранит целые как float)
    if isinstance(raw, float):
        if raw != int(raw):
            return None
        raw = int(raw)

    s = str(raw).strip()

    # Строка с ведущим минусом — битые данные
    if s.startswith("-"):
        return None

    # Убираем префикс "ИНН" с необязательным пробелом
    s = re.sub(r"^ИНН\s*", "", s, flags=re.IGNORECASE)

    # Убираем разделители: пробелы и дефисы
    s = re.sub(r"[\s\-]", "", s)

    return s if s else None


def validate_inn(inn: str) -> bool:
    """Проверяет, что нормализованный ИНН состоит из 10 (юрлицо) или 12 (физлицо) цифр."""
    return bool(re.fullmatch(r"\d{10}|\d{12}", inn))


def get_inn_type(inn: str) -> InnType:
    """Определяет тип субъекта по длине ИНН (вызывать только после validate_inn)."""
    return InnType.legal if len(inn) == 10 else InnType.individual
