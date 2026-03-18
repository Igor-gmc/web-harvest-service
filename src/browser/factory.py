import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from src.core.config import settings
from src.core.logger import get_logger

logger = get_logger(__name__)

# Где искать Chrome на Windows
_CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def _find_chrome() -> str:
    """Находит путь к системному Chrome."""
    for path in _CHROME_PATHS:
        if Path(path).exists():
            return path
    raise FileNotFoundError(
        "Chrome not found. Install Google Chrome or set CHROME_PATH in .env"
    )


class BrowserFactory:
    """Фабрика браузера — запускает чистый Chrome и подключается через CDP.

    Один экземпляр на весь процесс. Управляет лимитом открытых страниц.

    Почему CDP:
        Playwright при launch() добавляет --enable-automation и другие флаги,
        которые детектятся WAF/CDN (fedresurs.ru возвращает 403).
        Запуск Chrome напрямую через subprocess + подключение через CDP
        даёт fingerprint, неотличимый от обычного браузера.

    Lifecycle:
        start()      — запускает chrome.exe, подключается через CDP
        acquire_page() — берёт страницу (ждёт если лимит исчерпан)
        release_page() — закрывает страницу, освобождает слот
        close()      — отключается от CDP, убивает Chrome
    """

    def __init__(
        self,
        timeout_ms: int | None = None,
        cdp_port: int | None = None,
        max_pages: int | None = None,
    ) -> None:
        self._timeout_ms = timeout_ms if timeout_ms is not None else settings.browser_timeout_ms
        self._cdp_port = cdp_port or settings.cdp_port
        self._max_pages = max_pages or settings.max_browser_pages
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._chrome_process: subprocess.Popen | None = None
        self._user_data_dir: str | None = None
        self._page_semaphore: asyncio.Semaphore | None = None

    async def start(self) -> None:
        """Запускает Chrome и подключается через CDP."""
        chrome_path = _find_chrome()
        self._user_data_dir = tempfile.mkdtemp(prefix="chrome-harvest-")
        self._page_semaphore = asyncio.Semaphore(self._max_pages)

        cmd = [
            chrome_path,
            f"--remote-debugging-port={self._cdp_port}",
            f"--user-data-dir={self._user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
        ]

        self._chrome_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info("Chrome started: pid=%d, port=%d", self._chrome_process.pid, self._cdp_port)

        # Ждём пока CDP-порт станет доступен
        cdp_url = f"http://localhost:{self._cdp_port}"
        for attempt in range(20):
            await asyncio.sleep(0.5)
            try:
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.connect_over_cdp(cdp_url)
                logger.info(
                    "Connected to Chrome via CDP: %s (max_pages=%d)",
                    cdp_url, self._max_pages,
                )
                return
            except Exception:
                if self._playwright is not None:
                    await self._playwright.stop()
                    self._playwright = None
                if attempt < 19:
                    continue
                raise RuntimeError(
                    f"Chrome CDP not available on port {self._cdp_port} after 10s"
                )

    async def _get_context(self) -> BrowserContext:
        """Возвращает единственный context (создаёт при первом вызове)."""
        if self._context is None:
            contexts = self._browser.contexts
            if contexts:
                self._context = contexts[0]
            else:
                self._context = await self._browser.new_context()
            self._context.set_default_timeout(self._timeout_ms)
        return self._context

    async def acquire_page(self) -> Page:
        """Создаёт новую вкладку в существующем окне, ожидая если лимит исчерпан."""
        if self._browser is None:
            raise RuntimeError("BrowserFactory not started — call start() or use 'async with'")
        await self._page_semaphore.acquire()
        try:
            context = await self._get_context()
            page = await context.new_page()
            page.set_default_timeout(self._timeout_ms)
            return page
        except Exception:
            self._page_semaphore.release()
            raise

    async def release_page(self, page: Page) -> None:
        """Закрывает вкладку, освобождает слот."""
        try:
            await page.close()
        except Exception:
            logger.debug("Error closing page", exc_info=True)
        finally:
            self._page_semaphore.release()

    async def close(self) -> None:
        """Отключается от CDP и убивает процесс Chrome."""
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
            logger.info("Disconnected from CDP")
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        if self._chrome_process is not None:
            self._chrome_process.terminate()
            try:
                self._chrome_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._chrome_process.kill()
            logger.info("Chrome process terminated: pid=%d", self._chrome_process.pid)
            self._chrome_process = None
        if self._user_data_dir is not None:
            shutil.rmtree(self._user_data_dir, ignore_errors=True)
            self._user_data_dir = None

    async def __aenter__(self) -> "BrowserFactory":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # noqa: ANN001
        await self.close()
