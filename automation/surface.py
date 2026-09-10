"""The perceive/act seam.

Everything above this file — replay, discovery, conditions, handoff —
speaks only to this protocol. That is what lets the same recorded flow run
against Playwright today and an accessibility-tree desktop adapter later
without touching the artifact schema.
"""
from __future__ import annotations

from typing import Callable, Protocol

from pydantic import BaseModel, ConfigDict

from automation.models import LocatorSpec


class LocatorNotFound(Exception):
    def __init__(self, spec: LocatorSpec):
        super().__init__(f"no unique visible element for {spec.primary.kind}")
        self.spec = spec


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str
    title: str
    a11y: str
    screenshot_path: str | None = None


class Surface(Protocol):
    def observe(self, screenshot: bool = True) -> Observation: ...
    def navigate(self, url: str, timeout_ms: int) -> None: ...
    def click(self, spec: LocatorSpec, timeout_ms: int) -> None: ...
    def fill(self, spec: LocatorSpec, value: str, timeout_ms: int) -> None: ...
    def select(self, spec: LocatorSpec, value: str, timeout_ms: int) -> None: ...
    def text_of(self, spec: LocatorSpec, timeout_ms: int) -> str: ...
    def is_visible(self, spec: LocatorSpec, timeout_ms: int) -> bool: ...
    def page_contains(self, text: str) -> bool: ...
    def current_url(self) -> str: ...
    def screenshot(self, path: str, mask: list[LocatorSpec] | None = None) -> str: ...
    def on_navigation(self, callback) -> Callable[[], None]: ...


# --- appended to automation/surface.py -------------------------------------
from playwright.sync_api import Error as PWError
from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

MAX_A11Y_CHARS = 6_000


class PlaywrightSurface:
    """One headed Chromium context.

    Observation returns the accessibility tree, never the DOM. Claude can
    therefore only describe targets in terms this tree exposes, which is
    what makes recorded locators portable to surfaces that have no DOM.
    """

    def __init__(self, headless: bool = False, viewport: tuple[int, int] = (1280, 900)):
        self._headless = headless
        self._viewport = viewport
        self._pw = None
        self._browser = None
        self._page = None

    def __enter__(self) -> "PlaywrightSurface":
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless)
        context = self._browser.new_context(
            viewport={"width": self._viewport[0], "height": self._viewport[1]}
        )
        self._page = context.new_page()
        # An unhandled dialog blocks every subsequent command. Refuse it and
        # let the runner classify the situation rather than hanging.
        self._page.on("dialog", lambda d: d.dismiss())
        return self

    def __exit__(self, *exc) -> None:
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    @property
    def page(self):
        return self._page

    # --- perception -------------------------------------------------------
    def observe(self, screenshot: bool = True) -> Observation:
        return Observation(
            url=self._page.url,
            title=self._page.title(),
            a11y=self._page.locator("body").aria_snapshot()[:MAX_A11Y_CHARS],
            screenshot_path=None,
        )

    # --- locator resolution ----------------------------------------------
    def _resolve(self, spec: LocatorSpec, timeout_ms: int):
        """Try the primary locator, then the single declared fallback.

        A locator that matches nothing and a locator that matches several
        elements are the same failure: replay cannot know which control was
        meant, and guessing is how automation clicks the wrong button.
        """
        for locator_def in (spec.primary, spec.fallback):
            if locator_def is None:
                continue
            candidate = self._build(locator_def)
            visible = candidate.filter(visible=True)
            try:
                visible.wait_for(state="visible", timeout=timeout_ms)
                if visible.count() == 1:
                    return visible
            except (PWTimeout, PWError):
                continue
        raise LocatorNotFound(spec)

    def _build(self, d):
        page = self._page
        if d.kind == "role_name":
            return page.get_by_role(d.role, name=d.name, exact=d.exact)
        if d.kind == "label":
            return page.get_by_label(d.value, exact=d.exact)
        if d.kind == "placeholder":
            return page.get_by_placeholder(d.value, exact=d.exact)
        if d.kind == "text":
            return page.get_by_text(d.value, exact=d.exact)
        return page.locator(d.value)

    # --- actions ----------------------------------------------------------
    def navigate(self, url: str, timeout_ms: int) -> None:
        self._page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")

    def click(self, spec: LocatorSpec, timeout_ms: int) -> None:
        self._resolve(spec, timeout_ms).click(timeout=timeout_ms)

    def fill(self, spec: LocatorSpec, value: str, timeout_ms: int) -> None:
        self._resolve(spec, timeout_ms).fill(value, timeout=timeout_ms)

    def select(self, spec: LocatorSpec, value: str, timeout_ms: int) -> None:
        self._resolve(spec, timeout_ms).select_option(value, timeout=timeout_ms)

    def text_of(self, spec: LocatorSpec, timeout_ms: int) -> str:
        return self._resolve(spec, timeout_ms).inner_text(timeout=timeout_ms).strip()

    def is_visible(self, spec: LocatorSpec, timeout_ms: int) -> bool:
        try:
            self._resolve(spec, timeout_ms)
            return True
        except LocatorNotFound:
            return False

    def page_contains(self, text: str) -> bool:
        return text in self._page.inner_text("body")

    def current_url(self) -> str:
        return self._page.url

    def screenshot(self, path: str, mask: list[LocatorSpec] | None = None) -> str:
        masks = []
        for spec in mask or []:
            try:
                masks.append(self._resolve(spec, 1_000))
            except LocatorNotFound:
                continue
        self._page.screenshot(path=path, mask=masks or None)
        return path

    def on_navigation(self, callback) -> Callable[[], None]:
        def handler(frame):
            if frame == self._page.main_frame:
                callback(frame.url)

        self._page.on("framenavigated", handler)
        return lambda: self._page.remove_listener("framenavigated", handler)
