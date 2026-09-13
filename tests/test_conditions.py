# tests/test_conditions.py
import pytest
from automation.conditions import evaluate
from automation.models import ConditionSpec, Locator, LocatorSpec
from tests.fakes import FakeSurface


def _loc(name):
    return LocatorSpec(primary=Locator(kind="role_name", role="heading", name=name))


def test_url_matches():
    s = FakeSurface(url="https://automationexercise.com/checkout")
    assert evaluate(ConditionSpec(kind="url_matches", pattern=r".*/checkout$"), s) is True
    assert evaluate(ConditionSpec(kind="url_matches", pattern=r".*/cart$"), s) is False


def test_visible_text():
    s = FakeSurface(page_text="ACCOUNT CREATED!")
    assert evaluate(ConditionSpec(kind="visible_text", text="ACCOUNT CREATED!"), s) is True
    assert evaluate(ConditionSpec(kind="visible_text", text="ACCOUNT DELETED!"), s) is False


def test_element_visible_and_absent_are_inverses():
    s = FakeSurface(visible={"Blue Top"})
    cond_v = ConditionSpec(kind="element_visible", target=_loc("Blue Top"))
    cond_a = ConditionSpec(kind="element_absent", target=_loc("Blue Top"))
    assert evaluate(cond_v, s) is True
    assert evaluate(cond_a, s) is False


def test_value_equals_reads_element_text():
    s = FakeSurface(text_values={"Total": "Rs. 500"})
    cond = ConditionSpec(kind="value_equals", target=_loc("Total"), expected="Rs. 500")
    assert evaluate(cond, s) is True


def test_missing_element_is_false_not_an_exception():
    # A condition asking "is this visible?" about an element that does not
    # exist has a correct answer: no. Raising here would turn every
    # legitimate absence into a crash.
    s = FakeSurface(visible=set())
    assert evaluate(ConditionSpec(kind="element_visible", target=_loc("Ghost")), s) is False
    assert evaluate(ConditionSpec(kind="element_absent", target=_loc("Ghost")), s) is True
