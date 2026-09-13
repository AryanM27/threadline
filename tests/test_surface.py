import pytest
from inspect import signature

import automation.surface as surface_module
from automation.surface import Observation, PlaywrightSurface, UnexpectedDialog


def test_observation_contract_is_accessibility_only():
    assert list(signature(PlaywrightSurface.observe).parameters) == ["self"]
    assert "screenshot_path" not in Observation.model_fields


def test_playwright_navigation_timeout_is_normalized_to_builtin_timeout():
    class Page:
        def goto(self, *args, **kwargs):
            raise surface_module.PWTimeout("navigation timed out")

    surface = PlaywrightSurface()
    surface._page = Page()

    with pytest.raises(TimeoutError, match="navigation timed out"):
        surface.navigate("https://automationexercise.com", 1000)


def test_an_intercepted_click_is_reported_as_blocked_not_merely_timed_out():
    from automation.surface import ActionBlocked

    class Locator:
        def click(self, **kwargs):
            raise surface_module.PWTimeout(
                "locator.click: Timeout 3000ms exceeded.\nCall log:\n"
                "  - <div id=\"overlay\">…</div> intercepts pointer events\n"
                "  - retrying click action"
            )

    surface = PlaywrightSurface()
    surface._page = object()
    surface._resolve = lambda spec, timeout_ms: Locator()

    with pytest.raises(ActionBlocked):
        surface.click(None, 3000)
    assert issubclass(ActionBlocked, TimeoutError)


def test_a_click_that_dispatched_after_interception_stays_a_timeout():
    from automation.surface import ActionBlocked

    class Locator:
        def click(self, **kwargs):
            raise surface_module.PWTimeout(
                "locator.click: Timeout 3000ms exceeded.\nCall log:\n"
                "  - <div id=\"overlay\">…</div> intercepts pointer events\n"
                "  - click action done\n"
                "  - waiting for scheduled navigations to finish"
            )

    surface = PlaywrightSurface()
    surface._page = object()
    surface._resolve = lambda spec, timeout_ms: Locator()

    with pytest.raises(TimeoutError) as caught:
        surface.click(None, 3000)
    assert not isinstance(caught.value, ActionBlocked)


def test_a_plain_click_timeout_stays_a_timeout():
    from automation.surface import ActionBlocked

    class Locator:
        def click(self, **kwargs):
            raise surface_module.PWTimeout("locator.click: Timeout 3000ms exceeded.")

    surface = PlaywrightSurface()
    surface._page = object()
    surface._resolve = lambda spec, timeout_ms: Locator()

    with pytest.raises(TimeoutError) as caught:
        surface.click(None, 3000)
    assert not isinstance(caught.value, ActionBlocked)


def test_unexpected_dialog_is_dismissed_and_reported_by_the_surface():
    class Dialog:
        message = "Are you sure?"
        dismissed = False

        def dismiss(self):
            self.dismissed = True

    class Page:
        def goto(self, *args, **kwargs):
            return None

    surface = PlaywrightSurface()
    surface._page = Page()
    dialog = Dialog()

    surface._handle_dialog(dialog)

    assert dialog.dismissed is True
    with pytest.raises(UnexpectedDialog, match="Are you sure"):
        surface.navigate("https://automationexercise.com", 1000)


@pytest.mark.parametrize("read", [
    lambda surface: surface.is_visible(None, 1000),
    lambda surface: surface.current_url(),
], ids=["visibility", "url"])
def test_surface_reads_report_a_pending_unexpected_dialog(read):
    surface = PlaywrightSurface()
    surface._page = type("Page", (), {"url": "https://example.com"})()
    surface._resolve = lambda *args: object()
    surface._dialog_message = "Unexpected prompt"

    with pytest.raises(UnexpectedDialog, match="Unexpected prompt"):
        read(surface)
