import pytest
from pydantic import ValidationError
from automation.models import (
    CapabilityArtifact, Step, LocatorSpec, Locator, ConditionSpec,
    InputSpec, OutputSpec,
)


def _locator(kind="role_name", **kw):
    return LocatorSpec(primary=Locator(kind=kind, **kw))


def _minimal_artifact(**overrides):
    data = dict(
        schema_version="1.0",
        artifact_version=1,
        created_at="2026-09-09T10:00:00Z",
        discovery_run_id="run-abc",
        model_id="claude-opus-5",
        name="demo",
        description="A demo capability.",
        target={"vendor_product": "automationexercise", "base_url": "https://automationexercise.com"},
        inputs={"product": InputSpec(type="string")},
        outputs={"product_name": OutputSpec(type="string", from_step="s2")},
        steps=[
            Step(id="s1", action="navigate", url="https://automationexercise.com/products"),
            Step(id="s2", action="extract", target=_locator(role="heading", name="Blue Top"),
                 output_name="product_name"),
        ],
        success_condition=ConditionSpec(kind="visible_text", text="Blue Top"),
        business_outcomes=[],
    )
    data.update(overrides)
    return data


def test_valid_artifact_parses():
    art = CapabilityArtifact(**_minimal_artifact())
    assert art.name == "demo"
    assert art.steps[1].output_name == "product_name"


def test_unsupported_schema_version_rejected():
    with pytest.raises(ValidationError):
        CapabilityArtifact(**_minimal_artifact(schema_version="2.0"))


def test_unknown_field_rejected():
    with pytest.raises(ValidationError):
        CapabilityArtifact(**_minimal_artifact(surprise="nope"))


def test_provenance_fields_required():
    data = _minimal_artifact()
    del data["discovery_run_id"]
    with pytest.raises(ValidationError):
        CapabilityArtifact(**data)


def test_css_locator_requires_rationale():
    with pytest.raises(ValidationError):
        Step(id="s1", action="click", target=_locator(kind="css", value="div > .btn"))


def test_css_locator_accepted_with_rationale():
    step = Step(id="s1", action="click", target=_locator(kind="css", value="div > .btn"),
                locator_rationale="Control has no accessible name; vendor markup provides none.")
    assert step.target.primary.kind == "css"


def test_timeout_capped_at_30_seconds():
    with pytest.raises(ValidationError):
        Step(id="s1", action="click", target=_locator(role="button", name="Go"), timeout_ms=30001)


def test_extract_step_requires_output_name():
    with pytest.raises(ValidationError):
        Step(id="s1", action="extract", target=_locator(role="heading", name="X"))


def test_non_navigate_step_requires_target():
    with pytest.raises(ValidationError):
        Step(id="s1", action="click")


def test_integer_input_min_value_enforced_on_runtime_inputs():
    spec = InputSpec(type="integer", min_value=1)
    assert spec.validate_value(3) == 3
    with pytest.raises(ValueError):
        spec.validate_value(0)
