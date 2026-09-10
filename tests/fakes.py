"""Offline doubles. Every test in this suite runs without a browser."""
from __future__ import annotations

from automation.models import (
    BusinessOutcomeSpec, CapabilityArtifact, ConditionSpec, InputSpec,
    Locator, LocatorSpec, OutputSpec, Step,
)
from automation.surface import LocatorNotFound, Observation


def loc(name, role="button"):
    return LocatorSpec(primary=Locator(kind="role_name", role=role, name=name))


class FakeSurface:
    """A scriptable Surface.

    `script` maps a step-triggering action to the state that follows it, so
    a test can stage a not-found page, a session timeout, or a transient
    failure without a network.
    """

    def __init__(self, url="https://automationexercise.com/", title="Home",
                 page_text="", visible=None, text_values=None, a11y="",
                 fail_once_on=None):
        self._url = url
        self._title = title
        self._page_text = page_text
        self._visible = set(visible or ())
        self._text_values = dict(text_values or {})
        self._a11y = a11y
        self._fail_once_on = set(fail_once_on or ())
        self.actions: list[tuple] = []
        self.screenshots: list[str] = []
        self.screenshot_masks: list[list[LocatorSpec] | None] = []
        self._nav_callbacks: list = []

    # --- state staging used by tests -------------------------------------
    def set_state(self, *, url=None, page_text=None, visible=None, text_values=None):
        if url is not None:
            self._url = url
            for cb in tuple(self._nav_callbacks):
                cb(url)
        if page_text is not None:
            self._page_text = page_text
        if visible is not None:
            self._visible = set(visible)
        if text_values is not None:
            self._text_values = dict(text_values)

    # --- Surface protocol -------------------------------------------------
    def observe(self, screenshot=True):
        return Observation(url=self._url, title=self._title, a11y=self._a11y,
                           screenshot_path=None)

    def navigate(self, url, timeout_ms):
        self._trip("navigate")
        self.actions.append(("navigate", url))
        self.set_state(url=url)

    def click(self, spec, timeout_ms):
        self._trip("click")
        self.actions.append(("click", spec.primary.name or spec.primary.value))

    def fill(self, spec, value, timeout_ms):
        self._trip("fill")
        self.actions.append(("fill", spec.primary.name or spec.primary.value, value))

    def select(self, spec, value, timeout_ms):
        self.actions.append(("select", spec.primary.name or spec.primary.value, value))

    def text_of(self, spec, timeout_ms):
        key = spec.primary.name or spec.primary.value
        if key not in self._text_values:
            raise LocatorNotFound(spec)
        self.actions.append(("text_of", key))
        return self._text_values[key]

    def is_visible(self, spec, timeout_ms):
        return (spec.primary.name or spec.primary.value) in self._visible

    def page_contains(self, text):
        return text in self._page_text

    def current_url(self):
        return self._url

    def screenshot(self, path, mask=None):
        self.screenshot_masks.append(mask)
        self.screenshots.append(path)
        return path

    def on_navigation(self, callback):
        self._nav_callbacks.append(callback)
        return lambda: self._nav_callbacks.remove(callback) if callback in self._nav_callbacks else None

    def _trip(self, action):
        if action in self._fail_once_on:
            self._fail_once_on.discard(action)
            raise TimeoutError(f"transient failure on {action}")


def checkout_artifact(**overrides) -> CapabilityArtifact:
    """The fixture artifact used across replay, tenant, and catalog tests."""
    data = dict(
        schema_version="1.0",
        artifact_version=1,
        created_at="2026-09-09T10:00:00Z",
        discovery_run_id="run-fixture",
        model_id="claude-opus-5",
        provenance="discovered",
        name="prepare_product_checkout",
        description="Search a product, add it to the cart, and stop on checkout review.",
        target={"vendor_product": "automationexercise",
                "base_url": "https://automationexercise.com"},
        inputs={
            "email": InputSpec(type="string", sensitive=True),
            "password": InputSpec(type="string", sensitive=True),
            "product": InputSpec(type="string", max_length=80),
            "quantity": InputSpec(type="integer", min_value=1),
        },
        outputs={
            "product_name": OutputSpec(type="string", from_step="read_name"),
            "cart_total": OutputSpec(type="string", from_step="read_total"),
        },
        steps=[
            Step(id="go_products", action="navigate",
                 url="https://automationexercise.com/products",
                 expect=ConditionSpec(kind="url_matches", pattern=r".*/products")),
            Step(id="search", action="fill", target=loc("Search Product", role="textbox"),
                 value_from_input="product"),
            Step(id="submit_search", action="click", target=loc("Search"),
                 business_outcomes=[BusinessOutcomeSpec(
                     code="product_not_found",
                     when=ConditionSpec(kind="visible_text", text="No products found"),
                     description="The searched product does not exist.")]),
            Step(id="read_name", action="extract", target=loc("Product Name", role="heading"),
                 output_name="product_name"),
            Step(id="read_total", action="extract", target=loc("Total", role="cell"),
                 output_name="cart_total"),
        ],
        success_condition=ConditionSpec(kind="visible_text", text="Review Your Order"),
        business_outcomes=[
            BusinessOutcomeSpec(
                code="session_expired",
                when=ConditionSpec(kind="visible_text", text="Login to your account"),
                description="The authenticated session ended mid-flow."),
        ],
    )
    data.update(overrides)
    return CapabilityArtifact(**data)
