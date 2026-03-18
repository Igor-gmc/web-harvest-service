"""Вспомогательные функции для работы со страницей Playwright."""

import asyncio
import random
from pathlib import Path

from playwright.async_api import Page

from src.core.config import settings
from src.core.logger import get_logger

logger = get_logger(__name__)

# Маркеры блокировки — если title или body содержат такие фрагменты, сайт нас не пустил
_BLOCK_MARKERS = ["403", "forbidden", "access denied", "доступ запрещён", "доступ запрещен"]


async def detect_block(page: Page) -> str | None:
    """Проверяет, не заблокирован ли доступ к странице.

    Возвращает описание блокировки или None, если страница нормальная.
    """
    # Даём Angular/SPA время отрендерить title
    await human_delay(page, "block detection")

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

    Все селекторы из всех групп проверяются параллельно — побеждает тот,
    который найдётся первым. Это исключает задержки из-за последовательного
    перебора кандидатов внутри группы.

    groups: {"result_card": [...selectors...], "no_results": [...selectors...]}
    Возвращает (group_name, selector) для первого найденного, или (None, None).
    """
    async def _check_one(group_name: str, selector: str) -> tuple[str, str]:
        try:
            await page.wait_for_selector(selector, timeout=timeout_ms, state="attached")
            return group_name, selector
        except Exception:
            return None, None

    # Все селекторы из всех групп запускаем параллельно
    all_tasks = [
        asyncio.create_task(_check_one(name, sel))
        for name, candidates in groups.items()
        for sel in candidates
    ]

    # Ждём по одному, пока кто-то не найдёт совпадение
    while all_tasks:
        done, all_tasks_set = await asyncio.wait(
            all_tasks, return_when=asyncio.FIRST_COMPLETED,
        )
        all_tasks = list(all_tasks_set)

        for task in done:
            group_name, selector = task.result()
            if group_name is not None:
                logger.info("Race won by '%s' with selector: %s", group_name, selector)
                # Отменяем оставшиеся
                for t in all_tasks:
                    t.cancel()
                return group_name, selector

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


async def human_delay(page: Page, label: str = "") -> None:
    """Случайная задержка от 1 до human_delay_max_seconds для имитации пользователя."""
    max_sec = settings.human_delay_max_seconds
    delay = random.uniform(1, max(2, max_sec))
    logger.info("Human delay: %.1fs%s", delay, f" ({label})" if label else "")
    await page.wait_for_timeout(int(delay * 1000))


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
