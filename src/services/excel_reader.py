import openpyxl

from src.core.config import BASE_DIR, settings
from src.core.logger import get_logger
from src.schemas.input import ExcelReadResult, InputRow
from src.utils.validators import get_inn_type, normalize_inn, validate_inn

logger = get_logger(__name__)


def read_identifiers() -> ExcelReadResult:
    """Читает identifiers.xlsx, нормализует и валидирует ИНН.

    Строка 1 считается заголовком и пропускается.
    Плохие строки логируются и пропускаются — не валят весь импорт.

    Returns:
        ExcelReadResult со списком валидных InputRow и статистикой пропусков.
    """
    path = BASE_DIR / settings.input_xlsx_path
    logger.info("Reading identifiers from: %s", path)

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active

    result = ExcelReadResult()
    seen: set[str] = set()

    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        raw = row[0] if row else None
        result.total_rows += 1

        inn = normalize_inn(raw)
        if inn is None:
            logger.warning("Row %d: skipped - cannot normalize: %r", row_idx, raw)
            result.skipped_invalid += 1
            continue

        if not validate_inn(inn):
            logger.warning(
                "Row %d: skipped - invalid INN length (%d digits): %r -> %r",
                row_idx,
                len(inn),
                raw,
                inn,
            )
            result.skipped_invalid += 1
            continue

        if inn in seen:
            logger.warning("Row %d: skipped - duplicate INN: %s", row_idx, inn)
            result.skipped_duplicate += 1
            continue

        seen.add(inn)
        result.valid.append(InputRow(inn=inn, inn_type=get_inn_type(inn)))

    wb.close()

    logger.info(
        "Excel summary: total=%d, valid=%d, invalid=%d, duplicate=%d",
        result.total_rows,
        result.valid_count,
        result.skipped_invalid,
        result.skipped_duplicate,
    )
    return result
