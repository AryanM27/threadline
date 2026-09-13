"""Evaluate a ConditionSpec against a Surface.

Conditions are data. This module is the only place that interprets them,
so a new condition kind is one branch here plus one schema literal.
"""
from __future__ import annotations

import re

from automation.models import ConditionSpec
from automation.surface import LocatorNotFound, Surface

_PROBE_TIMEOUT_MS = 2_000


def evaluate(condition: ConditionSpec, surface: Surface) -> bool:
    kind = condition.kind
    if kind == "url_matches":
        return re.search(condition.pattern, surface.current_url()) is not None
    if kind == "visible_text":
        return surface.page_contains(condition.text)
    if kind == "element_visible":
        return _is_visible(condition, surface)
    if kind == "element_absent":
        return not _is_visible(condition, surface)
    if kind == "value_equals":
        try:
            actual = surface.text_of(condition.target, _PROBE_TIMEOUT_MS)
        except LocatorNotFound:
            return False
        return actual.strip() == condition.expected.strip()
    raise ValueError(f"unknown condition kind: {kind}")


def _is_visible(condition: ConditionSpec, surface: Surface) -> bool:
    try:
        return surface.is_visible(condition.target, _PROBE_TIMEOUT_MS)
    except LocatorNotFound:
        return False
