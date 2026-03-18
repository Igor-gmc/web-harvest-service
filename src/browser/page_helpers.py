"""Вспомогательные функции для работы со страницей Playwright."""

import asyncio
from pathlib import Path

from playwright.async_api import Page

from src.core.logger import get_logger

logger = get_logger(__name__)

# Маркеры блокировки — если title или body содержат такие фрагменты, сайт нас не пустил
_BLOCK_MARKERS = ["403", "forbidden", "access denied", "доступ запрещён", "доступ запрещен"]


async def detect_block(page: Page) -> str | None:
    """Проверяет, не заблокирован ли доступ к странице.

    Возвращает описание блокировки или None, если страница нормальная.
    """
    # Даём Angular/SPA время отрендерить title
    await page.wait_for_timeout(2000)

    title = (await page.title()).lower()
    for marker in _BLOCK_MARKERS:
        if marker in title:
            return f"Blocked (title contains '{marker}'): {await page.title()}"

    # Проверяем тело страницы — иногда title пустой при блокировке
    body_text = await page.text_content("body") or ""
    body_lower = body_text[:500].lower()
    for marker in _BLOCK_MARKERS:
        if marker in body_lower:
            return f"Blocked (body contains '{marker}')"

    # Проверяем HTML напрямую — страница может быть статической заглушкой CDN
    html = await page.content()
    html_lower = html[:1000].lower()
    for marker in _BLOCK_MARKERS:
        if marker in html_lower:
            return f"Blocked (HTML contains '{marker}')"

    return None


async def find_element_by_candidates(
    page: Page,
    candidates: list[str],
    label: str = "element",
    timeout_ms: int = 5000,
) -> str | None:
    """Перебирает список CSS-селекторов, возвращает первый найденный.

    Возвращает сам селектор (строку), если элемент найден, иначе None.
    """
    for selector in candidates:
        try:
            await page.wait_for_selector(selector, timeout=timeout_ms, state="attached")
            logger.info("Found %s with selector: %s", label, selector)
            return selector
        except Exception:
            logger.debug("Selector not matched for %s: %s", label, selector)
    logger.warning("No selector matched for %s (tried %d candidates)", label, len(candidates))
    return None


async def race_selectors(
    page: Page,
    groups: dict[str, list[str]],
    timeout_ms: int = 10000,
) -> tuple[str, str] | tuple[None, None]:
    """Ждёт первый найденный селектор из нескольких групп одновременно.

    groups: {"result_card": [...selectors...], "no_results": [...selectors...]}
    Возвращает (group_name, selector) для первого найденного, или (None, None).
    """
    async def _check_group(group_name: str, candidates: list[str]) -> tuple[str, str]:
        for selector in candidates:
            try:
                await page.wait_for_selector(selector, timeout=timeout_ms, state="attached")
                logger.info("Race won by '%s' with selector: %s", group_name, selector)
                return group_name, selector
            except Exception:
                pass
        return None, None

    tasks = [_check_group(name, candidates) for name, candidates in groups.items()]
    done, pending = await asyncio.wait(
        [asyncio.create_task(t) for t in tasks],
        return_when=asyncio.FIRST_COMPLETED,
    )

    # Отменяем оставшиеся
    for task in pending:
        task.cancel()

    # Берём первый завершённый с результатом
    for task in done:
        group_name, selector = task.result()
        if group_name is not None:
            return group_name, selector

    # Дожидаемся остальных (вдруг кто-то успел)
    for task in pending:
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    logger.warning("Race: no selector matched in any group")
    return None, None


async def type_into(page: Page, selector: str, text: str, delay_ms: int = 50) -> None:
    """Очищает поле и вводит текст посимвольно (имитация реального набора)."""
    await page.fill(selector, "")
    await page.type(selector, text, delay=delay_ms)
    logger.info("Typed '%s' into %s", text, selector)


async def click_element(page: Page, selector: str) -> None:
    """Кликает по элементу."""
    await page.click(selector)
    logger.info("Clicked: %s", selector)


DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "debug"


def _debug_path(filename: str) -> str:
    """Возвращает путь в debug/ папке, создаёт её при необходимости."""
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    return str(DEBUG_DIR / filename)


async def save_debug_screenshot(page: Page, filename: str) -> None:
    """Сохраняет screenshot в debug/ папку."""
    path = _debug_path(filename)
    await page.screenshot(path=path)
    logger.info("Debug screenshot saved: %s", path)


async def save_debug_html(page: Page, filename: str) -> None:
    """Сохраняет HTML в debug/ папку."""
    path = _debug_path(filename)
    html = await page.content()
    Path(path).write_text(html, encoding="utf-8")
    logger.info("Debug HTML saved: %s (%d bytes)", path, len(html))
