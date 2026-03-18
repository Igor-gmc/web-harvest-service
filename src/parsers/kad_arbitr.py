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
)
from src.browser.selectors import (
    KAD_CASE_LINK_CANDIDATES,
    KAD_CHRONO_DATE_SELECTOR,
    KAD_CHRONO_DOCUMENT_CANDIDATES,
    KAD_CHRONO_TABLE_CANDIDATES,
    KAD_LOGO_CANDIDATES,
    KAD_NO_RESULTS_CANDIDATES,
    KAD_RESULTS_TABLE_CANDIDATES,
    KAD_SEARCH_INPUT_CANDIDATES,
    KAD_URL,
)
from src.core.enums import CheckpointStep
from src.core.logger import get_logger
from src.db.models import ParseTask
from src.parsers.base import BaseParser, CheckpointFn
from src.schemas.kad_result import KadArbitrResultData

logger = get_logger(__name__)


class SiteAccessBlockedError(RuntimeError):
    pass


class NoResultsFoundError(RuntimeError):
    def __init__(self, message: str, page: Page):
        super().__init__(message)
        self.page = page


class SearchFailedError(RuntimeError):
    pass


class PageStructureChangedError(RuntimeError):
    pass


class NoDocumentsFoundError(RuntimeError):
    pass


class KadArbitrParser(BaseParser):
    """Парсер kad.arbitr.ru.

    Flow: открыть сайт → ввести номер дела → поиск → перейти в карточку дела →
    извлечь последнюю дату и документ из хронологии.
    """

    async def parse(
        self,
        task: ParseTask,
        factory: BrowserFactory,
        reuse_page: Page | None = None,
        reuse_on_results: bool = False,
        checkpoint: CheckpointFn | None = None,
    ) -> list[KadArbitrResultData]:
        self._checkpoint = checkpoint or self._noop_checkpoint
        self._factory = factory
        case_number = task.source_value

        logger.info("KadArbitrParser started: task_id=%d, case=%s", task.id, case_number)

        # Переиспользуем page если передали, иначе новая вкладка
        page = reuse_page or await factory.acquire_page()

        try:
            # Этап 1: Поиск
            await self._open_and_search(page, task, case_number)
            # Этап 2: Переход в карточку дела
            page = await self._open_case_card(page, task)
            # Этап 3: Извлечение данных из хронологии
            doc_date, doc_name, doc_title = await self._extract_last_document(page, task)
            # Этап 4: Возврат на главную для переиспользования
            await self._navigate_to_main(page, task)
        except (NoResultsFoundError, SiteAccessBlockedError, SearchFailedError,
                PageStructureChangedError, NoDocumentsFoundError):
            await factory.release_page(page)
            self.reuse_page = None
            raise
        except Exception:
            await factory.release_page(page)
            self.reuse_page = None
            raise

        self.reuse_page = page

        now = datetime.now(timezone.utc)
        result = KadArbitrResultData(
            task_id=task.id,
            case_number=case_number,
            parsed_at=now,
            document_date=doc_date,
            document_name=doc_name,
            document_title=doc_title,
        )

        logger.info(
            "KadArbitrParser finished: task_id=%d, case=%s, doc_date=%s, doc_name=%s",
            task.id, case_number, doc_date, doc_name,
        )
        return [result]

    # ------------------------------------------------------------------
    # Этап 1: Поиск
    # ------------------------------------------------------------------

    async def _open_and_search(
        self, page: Page, task: ParseTask, case_number: str,
    ) -> None:
        """Открыть kad.arbitr.ru, ввести номер дела, запустить поиск."""

        # Если page уже на главной kad.arbitr.ru — пропускаем goto
        if page.url.startswith(KAD_URL.rstrip("/")):
            logger.info("Already on kad.arbitr.ru, skip_goto=True, task_id=%d", task.id)
        else:
            logger.info("Opening %s ...", KAD_URL)
            await page.goto(KAD_URL, wait_until="domcontentloaded")
            logger.info("Page loaded: title=%s, url=%s", await page.title(), page.url)

            block = await detect_block(page)
            if block:
                await save_debug_screenshot(page, f"kad_blocked_{task.id}.png")
                raise SiteAccessBlockedError(block)

        await self._checkpoint(CheckpointStep.site_opened, {"url": page.url})

        # Найти поле поиска
        search_sel = await find_element_by_candidates(
            page, KAD_SEARCH_INPUT_CANDIDATES, "kad_search_input", timeout_ms=10000,
        )
        if not search_sel:
            await save_debug_screenshot(page, f"kad_no_search_input_{task.id}.png")
            await save_debug_html(page, f"kad_no_search_input_{task.id}.html")
            raise SearchFailedError(f"Search input not found, task_id={task.id}")

        # Ввести номер дела (jQuery — keyboard.type вместо fill)
        await page.click(search_sel)
        await page.wait_for_timeout(300)
        await page.keyboard.type(case_number, delay=80)
        logger.info("Case number entered: %s, task_id=%d", case_number, task.id)

        await self._checkpoint(CheckpointStep.search_submitted, {"case_number": case_number})

        # Enter
        await page.keyboard.press("Enter")
        logger.info("Search triggered via Enter, task_id=%d", task.id)

        await human_delay(page, "after search Enter")

        # Ждём реакцию
        group, selector = await race_selectors(
            page,
            {
                "results": KAD_RESULTS_TABLE_CANDIDATES,
                "case_link": KAD_CASE_LINK_CANDIDATES,
                "no_results": KAD_NO_RESULTS_CANDIDATES,
            },
            timeout_ms=15000,
        )

        logger.info(
            "After search: url=%s, race=%s, selector=%s, task_id=%d",
            page.url, group, selector, task.id,
        )

        await save_debug_screenshot(page, f"kad_after_search_{task.id}.png")

        if group == "no_results":
            raise NoResultsFoundError(f"No results for case {case_number}", page)

        if group is None:
            await save_debug_html(page, f"kad_search_timeout_{task.id}.html")
            raise SearchFailedError(f"Search timeout for case {case_number}, task_id={task.id}")

        await self._checkpoint(CheckpointStep.results_loaded, {"group": group})

    # ------------------------------------------------------------------
    # Этап 2: Переход в карточку дела
    # ------------------------------------------------------------------

    async def _open_case_card(self, page: Page, task: ParseTask) -> Page:
        """Кликнуть ссылку на дело, перейти в карточку."""

        case_link_sel = await find_element_by_candidates(
            page, KAD_CASE_LINK_CANDIDATES, "kad_case_link", timeout_ms=10000,
        )
        if not case_link_sel:
            await save_debug_screenshot(page, f"kad_no_case_link_{task.id}.png")
            raise PageStructureChangedError(f"Case link not found, task_id={task.id}")

        # Убрать target="_blank" чтобы навигация была в той же вкладке
        await page.evaluate(
            """(sel) => {
                const el = document.querySelector(sel);
                if (el) el.removeAttribute('target');
            }""",
            case_link_sel,
        )

        await human_delay(page, "before case card click")
        await click_element(page, case_link_sel)
        logger.info("Case link clicked, task_id=%d", task.id)

        # Дождаться загрузки карточки — URL изменится на /Card/...
        await page.wait_for_url("**/Card/**", timeout=15000)
        logger.info("Case card loaded: url=%s, task_id=%d", page.url, task.id)

        await human_delay(page, "card rendering")
        await save_debug_screenshot(page, f"kad_case_card_{task.id}.png")

        await self._checkpoint(CheckpointStep.card_opened, {"url": page.url})
        return page

    # ------------------------------------------------------------------
    # Этап 3: Извлечение данных из хронологии
    # ------------------------------------------------------------------

    async def _extract_last_document(
        self, page: Page, task: ParseTask,
    ) -> tuple[datetime | None, str | None, str | None]:
        """Найти хронологию, извлечь последнюю дату и документ."""

        # 1. Дождаться хронологии
        chrono_sel = await find_element_by_candidates(
            page, KAD_CHRONO_TABLE_CANDIDATES, "kad_chrono_table", timeout_ms=10000,
        )
        if not chrono_sel:
            await save_debug_screenshot(page, f"kad_no_chrono_{task.id}.png")
            await save_debug_html(page, f"kad_no_chrono_{task.id}.html")
            raise PageStructureChangedError(f"Chrono table not found, task_id={task.id}")

        logger.info("Chrono table found: %s, task_id=%d", chrono_sel, task.id)

        # 2. Собрать все даты
        date_elements = await page.query_selector_all(KAD_CHRONO_DATE_SELECTOR)
        logger.info("Found %d date elements, task_id=%d", len(date_elements), task.id)

        if not date_elements:
            await save_debug_screenshot(page, f"kad_no_dates_{task.id}.png")
            await save_debug_html(page, f"kad_no_dates_{task.id}.html")
            raise PageStructureChangedError(f"No dates in chrono, task_id={task.id}")

        # 3. Парсить даты, найти максимальную
        best_date: datetime | None = None
        best_element = None

        for el in date_elements:
            text = (await el.text_content() or "").strip()
            try:
                parsed = datetime.strptime(text, "%d.%m.%Y").replace(tzinfo=timezone.utc)
                if best_date is None or parsed > best_date:
                    best_date = parsed
                    best_element = el
                logger.debug("Date parsed: %s -> %s", text, parsed)
            except ValueError:
                logger.warning("Cannot parse date: '%s', task_id=%d", text, task.id)

        if best_date is None or best_element is None:
            raise NoDocumentsFoundError(f"No valid dates in chrono for case, task_id={task.id}")

        logger.info("Latest date: %s, task_id=%d", best_date.strftime("%d.%m.%Y"), task.id)

        # 4. Найти документ рядом с этой датой
        #    Идём вверх по DOM от span.b-reg-date до ближайшего контейнера строки,
        #    затем ищем h2.b-case-result a в соседних элементах.
        doc_info = await page.evaluate(
            """(dateEl) => {
                // Поднимаемся до строки хронологии (ищем контейнер с классом b-case-result рядом)
                let node = dateEl;
                for (let i = 0; i < 10; i++) {
                    node = node.parentElement;
                    if (!node) return null;
                    const docEl = node.querySelector('h2.b-case-result a');
                    if (docEl) {
                        return {
                            name: docEl.textContent.trim(),
                            href: docEl.getAttribute('href') || null,
                        };
                    }
                }
                return null;
            }""",
            best_element,
        )

        document_name = None
        document_title = None

        if doc_info:
            document_name = doc_info.get("name")
            document_title = doc_info.get("href")
            logger.info(
                "Document found: name='%s', href='%s', task_id=%d",
                document_name[:80] if document_name else None,
                document_title[:80] if document_title else None,
                task.id,
            )
        else:
            logger.warning("No document found near latest date, task_id=%d", task.id)

        await self._checkpoint(CheckpointStep.data_extracted, {
            "date": best_date.strftime("%d.%m.%Y"),
            "document_name": document_name,
        })

        return best_date, document_name, document_title

    # ------------------------------------------------------------------
    # Этап 4: Возврат на главную
    # ------------------------------------------------------------------

    async def _navigate_to_main(self, page: Page, task: ParseTask) -> None:
        """Кликнуть логотип 'Электронное правосудие' для возврата на главную."""
        logo_sel = await find_element_by_candidates(
            page, KAD_LOGO_CANDIDATES, "kad_logo", timeout_ms=5000,
        )
        if not logo_sel:
            logger.warning("Logo not found, cannot return to main, task_id=%d", task.id)
            return

        await human_delay(page, "before logo click")
        await click_element(page, logo_sel)
        logger.info("Logo clicked, task_id=%d", task.id)

        await page.wait_for_url("**/kad.arbitr.ru/**", timeout=10000)
        logger.info("Back on main page: url=%s, task_id=%d", page.url, task.id)

    @staticmethod
    async def _noop_checkpoint(step: CheckpointStep, data: dict | None = None) -> None:
        pass
