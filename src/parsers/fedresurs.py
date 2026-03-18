import re
from datetime import datetime, timezone

from playwright.async_api import Page

from src.browser.factory import BrowserFactory
from src.browser.page_helpers import (
    click_element,
    detect_block,
    find_element_by_candidates,
    human_delay,
    race_selectors,
    save_debug_html,
    save_debug_screenshot,
    type_into,
)
from src.browser.selectors import (
    FEDRESURS_BANKRUPTCY_BLOCK_CANDIDATES,
    FEDRESURS_CASE_NUMBER_CANDIDATES,
    FEDRESURS_ENTITY_LINK_CANDIDATES,
    FEDRESURS_LOGO_CANDIDATES,
    FEDRESURS_NO_RESULTS_CANDIDATES,
    FEDRESURS_PUBLICATIONS_CANDIDATES,
    FEDRESURS_RESULT_CARD_CANDIDATES,
    FEDRESURS_SEARCH_BUTTON_CANDIDATES,
    FEDRESURS_SEARCH_INPUT_CANDIDATES,
    FEDRESURS_TAB_PANEL_CANDIDATES,
)
from src.core.enums import CheckpointStep
from src.core.logger import get_logger
from src.db.models import ParseTask
from src.parsers.base import BaseParser, CheckpointFn
from src.schemas.results import FedresursResultData

logger = get_logger(__name__)

FEDRESURS_URL = "https://fedresurs.ru/"

# Паттерн даты вида "от DD.MM.YYYY"
_DATE_PATTERN = re.compile(r"от\s+(\d{2}\.\d{2}\.\d{4})")


class SiteAccessBlockedError(RuntimeError):
    """Сайт заблокировал доступ (403, капча, гео-блок)."""


class PageStructureChangedError(RuntimeError):
    """Страница загрузилась, но ожидаемые элементы не найдены."""


class SearchFailedError(RuntimeError):
    """Поиск не дал реакции от сайта."""


class NoResultsFoundError(RuntimeError):
    """По данному ИНН ничего не найдено."""

    def __init__(self, message: str, page: Page | None = None) -> None:
        super().__init__(message)
        self.page = page


class NoBankruptcyDataError(RuntimeError):
    """Карточка есть, но сведений о банкротстве нет."""


class FedresursParser(BaseParser):
    """Парсер fedresurs.ru.

    Flow: главная → поиск → результаты → карточка → извлечение данных о банкротстве.
    Все секции карточки находятся на одной странице (no tab click needed).
    """

    async def parse(
        self,
        task: ParseTask,
        factory: BrowserFactory,
        reuse_page: Page | None = None,
        reuse_on_results: bool = False,
        checkpoint: CheckpointFn | None = None,
    ) -> list[FedresursResultData]:
        self._checkpoint = checkpoint or self._noop_checkpoint
        inn = task.source_value
        logger.info("FedresursParser started: task_id=%d, inn=%s", task.id, inn)

        page = reuse_page or await factory.acquire_page()
        self.reuse_page: Page | None = None
        try:
            if reuse_on_results:
                # Повторный поиск на уже открытой странице результатов
                await self._search_on_results_page(page, task)
            else:
                # Шаги 1–9: поиск → результаты → открытие карточки
                await self._open_entity_card(
                    page, task, skip_goto=(reuse_page is not None),
                )

            # Шаг 10: извлечение данных о банкротстве (секция уже на странице)
            case_number, last_date = await self._extract_bankruptcy_data(page, task)
        except NoResultsFoundError:
            # Не закрываем страницу — передаём её для переиспользования
            raise
        except Exception:
            await factory.release_page(page)
            raise

        # Успех — возвращаемся на главную для переиспользования вкладки
        await self._navigate_to_main(page, task)
        self.reuse_page = page

        now = datetime.now(timezone.utc)
        results = [
            FedresursResultData(
                task_id=task.id,
                inn=inn,
                case_number=case_number,
                parsed_at=now,
                last_publication_date=last_date,
            )
        ]

        logger.info(
            "FedresursParser finished: task_id=%d, case=%s, last_date=%s",
            task.id, case_number, last_date,
        )
        return results

    @staticmethod
    async def _noop_checkpoint(step: CheckpointStep, data: dict | None = None) -> None:
        pass

    # ──────────────────────────────────────────────────────────────────────
    # Подэтап 1: главная → поиск → результаты → карточка
    # ──────────────────────────────────────────────────────────────────────

    async def _open_entity_card(
        self, page: Page, task: ParseTask, skip_goto: bool = False,
    ) -> None:
        inn = task.source_value

        if skip_goto:
            # Уже на главной (после клика по логотипу) — не перезагружаем
            logger.info("Already on main page, skip_goto=True, task_id=%d", task.id)
        else:
            # --- Шаг 1: Открываем fedresurs.ru ---
            logger.info("Opening %s ...", FEDRESURS_URL)
            await page.goto(FEDRESURS_URL, wait_until="networkidle", timeout=60000)
            title = await page.title()
            current_url = page.url
            logger.info("Page loaded: title=%s, url=%s", title, current_url)

            # --- Шаг 2: Детекция блокировки ---
            block_reason = await detect_block(page)
            if block_reason is not None:
                await save_debug_screenshot(page, "fedresurs_blocked.png")
                await save_debug_html(page, "fedresurs_blocked.html")
                logger.error(
                    "FedresursParser: site blocked, task_id=%d. %s", task.id, block_reason
                )
                raise SiteAccessBlockedError(
                    f"{block_reason} | url={current_url} | See debug/fedresurs_blocked.png"
                )

        await self._checkpoint(CheckpointStep.site_opened, {"inn": inn})

        # --- Шаг 3: Находим поле ввода ---
        input_selector = await find_element_by_candidates(
            page, FEDRESURS_SEARCH_INPUT_CANDIDATES,
            label="search_input", timeout_ms=20000,
        )
        if input_selector is None:
            await save_debug_screenshot(page, "fedresurs_no_input.png")
            await save_debug_html(page, "fedresurs_no_input.html")
            raise PageStructureChangedError(
                f"Search input not found on {current_url}. See debug/fedresurs_no_input.png"
            )

        # --- Шаг 4: Вводим ИНН ---
        await type_into(page, input_selector, inn)
        logger.info("INN entered: %s, task_id=%d", inn, task.id)

        # --- Шаг 5: Кнопка поиска ---
        button_selector = await find_element_by_candidates(
            page, FEDRESURS_SEARCH_BUTTON_CANDIDATES,
            label="search_button", timeout_ms=5000,
        )
        if button_selector is not None:
            await click_element(page, button_selector)
            logger.info("Search button clicked, task_id=%d", task.id)
        else:
            logger.info("Search button not found, pressing Enter, task_id=%d", task.id)
            await page.press(input_selector, "Enter")

        await self._checkpoint(CheckpointStep.search_submitted, {"inn": inn})

        # --- Шаг 6: Ждём перехода на страницу результатов ---
        url_before = page.url
        try:
            await page.wait_for_url(lambda url: url != url_before, timeout=15000)
        except Exception:
            await human_delay(page, "fallback after search")
        logger.info("After search: url=%s, task_id=%d", page.url, task.id)

        # --- Шаг 7+8: Ждём загрузки результатов — карточка, "ничего не найдено" или панель вкладок ---
        # «Ничего не найдено» может появиться БЕЗ панели вкладок, поэтому
        # объединяем ожидание в один race.
        winner, selector = await race_selectors(
            page,
            {
                "result_card": FEDRESURS_RESULT_CARD_CANDIDATES,
                "no_results": FEDRESURS_NO_RESULTS_CANDIDATES,
                "tab_panel": FEDRESURS_TAB_PANEL_CANDIDATES,
            },
            timeout_ms=15000,
        )

        if winner == "no_results":
            await save_debug_screenshot(page, f"fedresurs_no_results_{task.id}.png")
            raise NoResultsFoundError(
                f"No results for INN {inn}. See debug/fedresurs_no_results_{task.id}.png",
                page=page,
            )

        if winner is None:
            await save_debug_screenshot(page, f"fedresurs_no_tabs_{task.id}.png")
            await save_debug_html(page, f"fedresurs_no_tabs_{task.id}.html")
            raise PageStructureChangedError(
                f"No results page elements found for INN {inn}. "
                f"See debug/fedresurs_no_tabs_{task.id}.png"
            )

        if winner == "tab_panel":
            # Панель вкладок нашлась — ждём карточку или «ничего не найдено»
            logger.info("Results page loaded (tab_panel), task_id=%d", task.id)
            await human_delay(page, "tab panel loaded")

            winner2, selector2 = await race_selectors(
                page,
                {
                    "result_card": FEDRESURS_RESULT_CARD_CANDIDATES,
                    "no_results": FEDRESURS_NO_RESULTS_CANDIDATES,
                },
                timeout_ms=10000,
            )

            if winner2 == "no_results":
                await save_debug_screenshot(page, f"fedresurs_no_results_{task.id}.png")
                raise NoResultsFoundError(
                    f"No results for INN {inn}. See debug/fedresurs_no_results_{task.id}.png",
                    page=page,
                )
            if winner2 is None:
                await save_debug_screenshot(page, f"fedresurs_empty_{task.id}.png")
                await save_debug_html(page, f"fedresurs_empty_{task.id}.html")
                raise PageStructureChangedError(
                    f"No cards and no 'not found' marker for INN {inn}."
                )
            selector = selector2

        logger.info("Result card found: %s, task_id=%d", selector, task.id)
        await self._checkpoint(CheckpointStep.results_loaded, {"inn": inn, "results_url": page.url})

        # --- Шаг 9: Клик "Вся информация" ---
        entity_link = await find_element_by_candidates(
            page, FEDRESURS_ENTITY_LINK_CANDIDATES,
            label="entity_link", timeout_ms=5000,
        )
        if entity_link is None:
            await save_debug_screenshot(page, f"fedresurs_no_link_{task.id}.png")
            raise PageStructureChangedError(
                f"Entity link not found for INN {inn}. See debug/fedresurs_no_link_{task.id}.png"
            )

        await human_delay(page, "before entity link click")
        url_before_card = page.url
        await click_element(page, entity_link)
        logger.info("Entity link clicked, task_id=%d", task.id)

        try:
            await page.wait_for_url(lambda url: url != url_before_card, timeout=30000)
        except Exception:
            await human_delay(page, "fallback after card click")

        logger.info("Entity card loaded: url=%s, task_id=%d", page.url, task.id)
        await self._checkpoint(CheckpointStep.card_opened, {"inn": inn, "entity_url": page.url})

        # Даём Angular дорендерить все секции карточки
        await human_delay(page, "card rendering")
        await save_debug_screenshot(page, f"fedresurs_card_{task.id}.png")

    # ──────────────────────────────────────────────────────────────────────
    # Возврат на главную через клик по логотипу (переиспользование вкладки)
    # ──────────────────────────────────────────────────────────────────────

    async def _navigate_to_main(self, page: Page, task: ParseTask) -> None:
        """Кликает по логотипу для возврата на главную страницу."""
        await human_delay(page, "before logo click")

        logo_selector = await find_element_by_candidates(
            page, FEDRESURS_LOGO_CANDIDATES,
            label="logo", timeout_ms=5000,
        )
        if logo_selector is None:
            logger.warning("Logo not found, falling back to goto, task_id=%d", task.id)
            await page.goto(FEDRESURS_URL, wait_until="networkidle", timeout=60000)
            return

        url_before = page.url
        await click_element(page, logo_selector)
        logger.info("Logo clicked, task_id=%d", task.id)

        try:
            await page.wait_for_url(lambda url: url != url_before, timeout=15000)
        except Exception:
            await human_delay(page, "fallback after logo click")

        logger.info("Back on main page: url=%s, task_id=%d", page.url, task.id)

    # ──────────────────────────────────────────────────────────────────────
    # Подэтап 1.5: повторный поиск на уже открытой странице результатов
    # ──────────────────────────────────────────────────────────────────────

    async def _search_on_results_page(self, page: Page, task: ParseTask) -> None:
        """Очищает поле ввода, вводит новый ИНН и ищет на странице результатов.

        Вызывается когда предыдущий ИНН дал «Ничего не найдено» и страница
        не закрывалась — переиспользуем вкладку для следующего ИНН.
        """
        inn = task.source_value
        logger.info("Reusing results page for new INN: %s, task_id=%d", inn, task.id)
        await human_delay(page, "before re-search")

        # --- Находим поле ввода на странице результатов ---
        input_selector = await find_element_by_candidates(
            page, FEDRESURS_SEARCH_INPUT_CANDIDATES,
            label="results_search_input", timeout_ms=10000,
        )
        if input_selector is None:
            raise PageStructureChangedError(
                f"Search input not found on results page for task_id={task.id}"
            )

        # --- Очищаем и вводим новый ИНН ---
        await type_into(page, input_selector, inn)
        logger.info("New INN entered on results page: %s, task_id=%d", inn, task.id)

        # --- Запускаем поиск нажатием Enter ---
        await page.press(input_selector, "Enter")
        logger.info("Search triggered via Enter on results page, task_id=%d", task.id)
        await self._checkpoint(CheckpointStep.search_submitted, {"inn": inn})

        # --- Ждём обновления результатов ---
        await human_delay(page, "after Enter re-search")

        # --- Ждём результатов: карточка, "ничего не найдено" или панель вкладок ---
        winner, selector = await race_selectors(
            page,
            {
                "result_card": FEDRESURS_RESULT_CARD_CANDIDATES,
                "no_results": FEDRESURS_NO_RESULTS_CANDIDATES,
                "tab_panel": FEDRESURS_TAB_PANEL_CANDIDATES,
            },
            timeout_ms=15000,
        )

        if winner == "no_results":
            await save_debug_screenshot(page, f"fedresurs_no_results_{task.id}.png")
            raise NoResultsFoundError(
                f"No results for INN {inn}. See debug/fedresurs_no_results_{task.id}.png",
                page=page,
            )

        if winner is None:
            await save_debug_screenshot(page, f"fedresurs_no_tabs_{task.id}.png")
            await save_debug_html(page, f"fedresurs_no_tabs_{task.id}.html")
            raise PageStructureChangedError(
                f"No results page elements after re-search for INN {inn}. "
                f"See debug/fedresurs_no_tabs_{task.id}.png"
            )

        if winner == "tab_panel":
            logger.info("Results page reloaded after re-search, task_id=%d", task.id)
            await human_delay(page, "tab panel loaded re-search")

            winner2, selector2 = await race_selectors(
                page,
                {
                    "result_card": FEDRESURS_RESULT_CARD_CANDIDATES,
                    "no_results": FEDRESURS_NO_RESULTS_CANDIDATES,
                },
                timeout_ms=10000,
            )

            if winner2 == "no_results":
                await save_debug_screenshot(page, f"fedresurs_no_results_{task.id}.png")
                raise NoResultsFoundError(
                    f"No results for INN {inn}. See debug/fedresurs_no_results_{task.id}.png",
                    page=page,
                )
            if winner2 is None:
                await save_debug_screenshot(page, f"fedresurs_empty_{task.id}.png")
                await save_debug_html(page, f"fedresurs_empty_{task.id}.html")
                raise PageStructureChangedError(
                    f"No cards and no 'not found' marker for INN {inn} after re-search."
                )
            selector = selector2

        logger.info("Result card found after re-search: %s, task_id=%d", selector, task.id)
        await self._checkpoint(CheckpointStep.results_loaded, {"inn": inn, "results_url": page.url})

        # --- Клик "Вся информация" ---
        entity_link = await find_element_by_candidates(
            page, FEDRESURS_ENTITY_LINK_CANDIDATES,
            label="entity_link", timeout_ms=5000,
        )
        if entity_link is None:
            await save_debug_screenshot(page, f"fedresurs_no_link_{task.id}.png")
            raise PageStructureChangedError(
                f"Entity link not found for INN {inn}. "
                f"See debug/fedresurs_no_link_{task.id}.png"
            )

        await human_delay(page, "before entity link click re-search")
        url_before_card = page.url
        await click_element(page, entity_link)
        logger.info("Entity link clicked (re-search), task_id=%d", task.id)

        try:
            await page.wait_for_url(lambda url: url != url_before_card, timeout=30000)
        except Exception:
            await human_delay(page, "fallback after card click re-search")

        logger.info("Entity card loaded (re-search): url=%s, task_id=%d", page.url, task.id)
        await self._checkpoint(CheckpointStep.card_opened, {"inn": inn, "entity_url": page.url})

        # Даём Angular дорендерить все секции карточки
        await human_delay(page, "card rendering re-search")
        await save_debug_screenshot(page, f"fedresurs_card_{task.id}.png")

    # ──────────────────────────────────────────────────────────────────────
    # Подэтап 2: извлечение данных о банкротстве со страницы карточки
    # ──────────────────────────────────────────────────────────────────────

    async def _extract_bankruptcy_data(
        self, page: Page, task: ParseTask,
    ) -> tuple[str, datetime | None]:
        inn = task.source_value

        block_selector = await find_element_by_candidates(
            page, FEDRESURS_BANKRUPTCY_BLOCK_CANDIDATES,
            label="bankruptcy_block", timeout_ms=5000,
        )
        if block_selector is None:
            await save_debug_screenshot(page, f"fedresurs_no_bankruptcy_{task.id}.png")
            await save_debug_html(page, f"fedresurs_no_bankruptcy_{task.id}.html")
            raise NoBankruptcyDataError(
                f"Bankruptcy section not found for INN {inn}. "
                f"See debug/fedresurs_no_bankruptcy_{task.id}.png"
            )
        logger.info("Bankruptcy block found: %s, task_id=%d", block_selector, task.id)
        await self._checkpoint(CheckpointStep.bankruptcy_found, {"inn": inn, "entity_url": page.url})

        case_number = await self._extract_case_number(page, task)
        last_date = await self._extract_last_publication_date(page, task)

        await self._checkpoint(CheckpointStep.data_extracted, {"inn": inn, "case_number": case_number})
        await save_debug_screenshot(page, f"fedresurs_bankruptcy_{task.id}.png")

        return case_number, last_date

    async def _extract_case_number(self, page: Page, task: ParseTask) -> str:
        case_selector = await find_element_by_candidates(
            page, FEDRESURS_CASE_NUMBER_CANDIDATES,
            label="case_number", timeout_ms=5000,
        )
        if case_selector is None:
            await save_debug_screenshot(page, f"fedresurs_no_case_{task.id}.png")
            await save_debug_html(page, f"fedresurs_no_case_{task.id}.html")
            raise PageStructureChangedError(
                f"Case number not found for INN {task.source_value}. "
                f"See debug/fedresurs_no_case_{task.id}.png"
            )

        case_element = await page.query_selector(case_selector)
        case_number = (await case_element.text_content() or "").strip()
        if not case_number:
            raise PageStructureChangedError(
                f"Case number element found but text empty for INN {task.source_value}."
            )
        logger.info("Case number: '%s', task_id=%d", case_number, task.id)
        return case_number

    async def _extract_last_publication_date(
        self, page: Page, task: ParseTask,
    ) -> datetime | None:
        pub_selector = await find_element_by_candidates(
            page, FEDRESURS_PUBLICATIONS_CANDIDATES,
            label="publications", timeout_ms=5000,
        )
        if pub_selector is None:
            logger.warning("No publications found, task_id=%d", task.id)
            return None

        pub_elements = await page.query_selector_all(pub_selector)
        if not pub_elements:
            logger.warning("Publications selector matched but no elements, task_id=%d", task.id)
            return None

        logger.info("Found %d publication(s), task_id=%d", len(pub_elements), task.id)

        # Извлекаем все даты и берём самую свежую (max)
        all_dates: list[datetime] = []
        for el in pub_elements:
            text = await el.text_content() or ""
            match = _DATE_PATTERN.search(text)
            if match:
                try:
                    dt = datetime.strptime(match.group(1), "%d.%m.%Y")
                    dt = dt.replace(tzinfo=timezone.utc)
                    all_dates.append(dt)
                except ValueError:
                    logger.debug("Failed to parse date: '%s'", match.group(1))

        if not all_dates:
            logger.warning("No dates extracted from publications, task_id=%d", task.id)
            return None

        last_date = max(all_dates)
        logger.info(
            "Last publication date: %s (from %d dates), task_id=%d",
            last_date.strftime("%d.%m.%Y"), len(all_dates), task.id,
        )
        return last_date
