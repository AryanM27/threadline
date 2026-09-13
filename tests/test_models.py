import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from automation.conditions import evaluate
from automation.models import (
    CapabilityArtifact, Step, LocatorSpec, Locator, ConditionSpec,
    InputSpec, OutputSpec,
)
from tests.fakes import FakeSurface, checkout_artifact


SHIPPED = sorted((Path(__file__).resolve().parents[1] / "evidence" / "artifacts").glob("*.json"))
REVIEWED = [path for path in SHIPPED if json.loads(path.read_text())["provenance"] == "hand_authored"]


def _shipped(name):
    path = Path(__file__).resolve().parents[1] / "evidence" / "artifacts" / f"{name}.json"
    return CapabilityArtifact(**json.loads(path.read_text()))


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: p.stem)
def test_every_shipped_artifact_validates_and_checkpoints_its_transitions(path):
    artifact = CapabilityArtifact(**json.loads(path.read_text()))
    unchecked = [s.id for s in artifact.steps
                 if s.action in ("navigate", "click") and s.expect is None
                 and not s.business_outcomes and s.risk == "safe"]
    assert unchecked == [], f"{path.stem}: state-changing steps without a checkpoint"


@pytest.mark.parametrize("path", REVIEWED, ids=lambda p: p.stem)
def test_every_reviewed_artifact_declares_at_least_one_fallback(path):
    artifact = CapabilityArtifact(**json.loads(path.read_text()))
    assert any(s.target and s.target.fallback for s in artifact.steps)


@pytest.mark.parametrize("path", REVIEWED, ids=lambda p: p.stem)
def test_no_reviewed_condition_uses_expected_as_a_comment(path):
    artifact = CapabilityArtifact(**json.loads(path.read_text()))
    conditions = [artifact.success_condition,
                  *(s.expect for s in artifact.steps if s.expect),
                  *(o.when for s in artifact.steps for o in s.business_outcomes),
                  *(o.when for o in artifact.business_outcomes)]
    assert all(c.expected is None for c in conditions if c.kind != "value_equals")


def test_registration_checkpoint_matches_the_observed_account_form_heading():
    artifact = _shipped("register_test_account")
    checkpoint = next(step.expect for step in artifact.steps if step.id == "s04")

    assert evaluate(checkpoint, FakeSurface(page_text="ENTER ACCOUNT INFORMATION"))


def test_registration_email_mask_covers_the_auto_populated_account_form_field():
    artifact = _shipped("register_test_account")
    email_target = next(step.target for step in artifact.steps if step.id == "s03")

    assert email_target.fallback == Locator(kind="css", value='input[data-qa="email"]')


def test_checkout_cart_total_selector_excludes_final_total_row():
    artifact = _shipped("prepare_product_checkout")
    total_target = next(step.target for step in artifact.steps if step.id == "s23")

    assert total_target.primary == Locator(
        kind="css", value=".cart_info tbody tr:not(:last-child) .cart_total_price"
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


def test_hand_authored_artifact_records_the_run_it_derives_from():
    artifact = checkout_artifact(
        provenance="hand_authored",
        derived_from="discovery-e4e5dc356f484e87b62933aa0b84ba1a",
    )
    assert artifact.derived_from == "discovery-e4e5dc356f484e87b62933aa0b84ba1a"


def test_a_discovered_artifact_cannot_claim_a_derivation():
    with pytest.raises(ValidationError):
        checkout_artifact(provenance="discovered", derived_from="discovery-abc")


def test_derived_from_defaults_to_none_so_existing_artifacts_still_validate():
    assert checkout_artifact().derived_from is None


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
