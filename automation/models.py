"""Typed contracts for capability artifacts, runtime inputs, and results.

This module holds data only. Nothing here touches a browser, the network,
or the filesystem — which is what makes the artifact contract testable in
isolation and reviewable by a human reading one file.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.0"

LocatorKind = Literal["role_name", "label", "placeholder", "text", "css"]
ActionType = Literal["navigate", "click", "fill", "select", "extract", "assert"]
ConditionKind = Literal[
    "url_matches", "visible_text", "element_visible", "element_absent", "value_equals"
]
Risk = Literal["safe", "requires_human"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Locator(Strict):
    """One way to identify a control.

    `role` and `name` apply to `role_name`; `value` carries the label text,
    placeholder text, visible text, or CSS selector for the other kinds.
    """
    kind: LocatorKind
    role: str | None = None
    name: str | None = None
    value: str | None = None
    exact: bool = False

    @model_validator(mode="after")
    def _check_fields(self) -> "Locator":
        if self.kind == "role_name":
            if not self.role or not self.name:
                raise ValueError("role_name locators require both role and name")
        elif not self.value:
            raise ValueError(f"{self.kind} locators require value")
        return self


class LocatorSpec(Strict):
    """A primary locator and at most one explicit fallback."""
    primary: Locator
    fallback: Locator | None = None

    def uses_css(self) -> bool:
        return self.primary.kind == "css" or (
            self.fallback is not None and self.fallback.kind == "css"
        )


class ConditionSpec(Strict):
    """A checkable state. Data, never executable code."""
    kind: ConditionKind
    pattern: str | None = None
    text: str | None = None
    target: LocatorSpec | None = None
    expected: str | None = None

    @model_validator(mode="after")
    def _check_fields(self) -> "ConditionSpec":
        required = {
            "url_matches": ("pattern",),
            "visible_text": ("text",),
            "element_visible": ("target",),
            "element_absent": ("target",),
            "value_equals": ("target", "expected"),
        }[self.kind]
        for field in required:
            if getattr(self, field) is None:
                raise ValueError(f"{self.kind} conditions require {field}")
        return self


class BusinessOutcomeSpec(Strict):
    """An expected result the caller needs to know about, not a failure."""
    code: str
    when: ConditionSpec
    description: str = ""


class Step(Strict):
    id: str
    action: ActionType
    url: str | None = None
    target: LocatorSpec | None = None
    value_from_input: str | None = None
    output_name: str | None = None
    expect: ConditionSpec | None = None
    business_outcomes: list[BusinessOutcomeSpec] = Field(default_factory=list)
    timeout_ms: int = Field(default=10_000, gt=0, le=30_000)
    risk: Risk = "safe"
    locator_rationale: str = ""

    @model_validator(mode="after")
    def _check_shape(self) -> "Step":
        if self.action == "navigate":
            if not self.url:
                raise ValueError("navigate steps require url")
        elif self.target is None:
            raise ValueError(f"{self.action} steps require target")

        if self.action == "extract" and not self.output_name:
            raise ValueError("extract steps require output_name")
        if self.action in ("fill", "select") and not self.value_from_input:
            raise ValueError(f"{self.action} steps require value_from_input")
        if self.target and self.target.uses_css() and not self.locator_rationale.strip():
            raise ValueError(
                "css locators require locator_rationale explaining why no "
                "accessible name was available"
            )
        return self


class InputSpec(Strict):
    type: Literal["string", "integer", "boolean"]
    required: bool = True
    sensitive: bool = False
    min_value: int | None = None
    max_length: int | None = None
    pattern: str | None = None

    def validate_value(self, value: Any) -> Any:
        """Check one runtime value against this spec. Raises ValueError."""
        import re

        if self.type == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("expected an integer")
            if self.min_value is not None and value < self.min_value:
                raise ValueError(f"expected >= {self.min_value}, got {value}")
        elif self.type == "boolean":
            if not isinstance(value, bool):
                raise ValueError("expected a boolean")
        else:
            if not isinstance(value, str):
                raise ValueError("expected a string")
            if self.max_length is not None and len(value) > self.max_length:
                raise ValueError(f"longer than {self.max_length} characters")
            if self.pattern is not None and not re.fullmatch(self.pattern, value):
                raise ValueError("does not match required pattern")
        return value


class OutputSpec(Strict):
    type: Literal["string", "integer", "number", "boolean"]
    from_step: str


class TargetSpec(Strict):
    vendor_product: str
    base_url: str
    supported_versions: str | None = None


class CapabilityArtifact(Strict):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    schema_version: Literal["1.0"]
    artifact_version: int = Field(ge=1)
    created_at: str
    discovery_run_id: str
    model_id: str
    provenance: Literal["discovered", "hand_authored"] = "discovered"
    name: str
    description: str
    target: TargetSpec
    inputs: dict[str, InputSpec]
    outputs: dict[str, OutputSpec]
    steps: list[Step] = Field(min_length=1)
    success_condition: ConditionSpec
    business_outcomes: list[BusinessOutcomeSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_references(self) -> "CapabilityArtifact":
        ids = [s.id for s in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step ids must be unique within an artifact")
        for step in self.steps:
            if step.value_from_input and step.value_from_input not in self.inputs:
                raise ValueError(f"step {step.id} references unknown input "
                                 f"{step.value_from_input!r}")
        for name, out in self.outputs.items():
            if out.from_step not in ids:
                raise ValueError(f"output {name!r} references unknown step "
                                 f"{out.from_step!r}")
        return self

    def sensitive_input_names(self) -> set[str]:
        return {name for name, spec in self.inputs.items() if spec.sensitive}


class TenantProfile(Strict):
    """Per-tenant specialization of a base artifact.

    Overrides replace named locators and conditions; they never fork the
    artifact, so one reviewed flow serves every tenant with a small diff.
    """
    tenant_id: str
    base_url: str
    product_version: str | None = None
    locator_overrides: dict[str, LocatorSpec] = Field(default_factory=dict)
    condition_overrides: dict[str, ConditionSpec] = Field(default_factory=dict)


class FailureDetail(Strict):
    step_id: str
    step_index: int
    error_code: str
    expected: str
    observed: str
    screenshot_path: str | None = None


class RecoveryRecord(Strict):
    step_id: str
    kind: Literal["interstitial_dismissed", "retried"]
    detail: str = ""


class HandoffSummary(Strict):
    operator: str
    accepted: bool
    description: str = ""
    url_trail: list[str] = Field(default_factory=list)
    before_screenshot: str | None = None
    after_screenshot: str | None = None


class RunResult(Strict):
    run_id: str
    capability: str
    status: Literal["success", "business_outcome", "failure"]
    outputs: dict[str, Any] = Field(default_factory=dict)
    outcome_code: str | None = None
    failure: FailureDetail | None = None
    recoveries: list[RecoveryRecord] = Field(default_factory=list)
    handoffs: list[HandoffSummary] = Field(default_factory=list)
    evidence_dir: str
