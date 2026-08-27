from pathlib import Path

from playwright.async_api import async_playwright

from app.runtime.base import ComputerRuntime
from app.services.playwright_browser import ensure_chromium, is_missing_browser_error


class PlaywrightRuntime(ComputerRuntime):
    def __init__(self) -> None:
        self._playwright = None
        self._context = None
        self._page = None

    async def open_profile(self, profile_path: Path, url: str | None = None) -> None:
        profile_path.mkdir(parents=True, exist_ok=True)
        try:
            await self._launch(profile_path, url)
        except Exception as exc:
            if not is_missing_browser_error(exc):
                raise
            ok, msg = ensure_chromium()
            if not ok:
                raise RuntimeError(msg) from exc
            await self.close()
            await self._launch(profile_path, url)

    async def _launch(self, profile_path: Path, url: str | None = None) -> None:
        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_path.resolve()),
            headless=False,
            viewport={"width": 1280, "height": 720},
        )
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        if url:
            await self._page.goto(url, wait_until="domcontentloaded")

    async def screenshot(self, output_path: Path) -> Path:
        if self._page is None:
            raise RuntimeError("Browser is not open")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        await self._page.screenshot(path=str(output_path))
        return output_path

    async def close(self) -> None:
        if self._context is not None:
            await self._context.close()
            self._context = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        self._page = None

    @property
    def page(self):
        return self._page
