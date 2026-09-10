from automation.evidence import EvidenceWriter
from automation.handoff import TerminalHandoff
from automation.models import ConditionSpec, HandoffSummary, OutputSpec, TenantProfile
from automation.policy import Policy, PolicyEngine
from automation.replay import ReplayRunner
from tests.fakes import FakeSurface, checkout_artifact, loc

INPUTS = {"email": "a@b.com", "password": "hunter2", "product": "Blue Top", "quantity": 1}


def _engine():
    return PolicyEngine(Policy(
        allowed_origins=[{"scheme": "https", "host": "automationexercise.com"}],
        denied_route_patterns=["/payment*"],
        allowed_actions=["navigate", "click", "fill", "select", "extract", "assert"],
    ))


def _runner(surface, tmp_path, artifact=None, **kw):
    artifact = artifact or checkout_artifact()
    return ReplayRunner(
        artifact=artifact,
        policy=_engine(),
        evidence=EvidenceWriter(tmp_path, "run-t", artifact.sensitive_input_names()),
        surface=surface,
        **kw,
    )


def _happy_surface():
    return FakeSurface(
        url="https://automationexercise.com/",
        page_text="Review Your Order",
        text_values={"Product Name": "Blue Top", "Total": "Rs. 500"},
    )


class _Handoff:
    def __init__(self, repair=None):
        self.calls = 0
        self._repair = repair

    def request(self, **kwargs):
        self.calls += 1
        if self._repair:
            self._repair(kwargs["surface"])
        return HandoffSummary(operator="operator", accepted=True)


class _CapturingHandoff:
    def __init__(self):
        self.kwargs = None

    def request(self, **kwargs):
        self.kwargs = kwargs
        return HandoffSummary(operator="", accepted=False)


class _MaskSurface(FakeSurface):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.screenshot_masks = []

    def screenshot(self, path, mask=None):
        self.screenshot_masks.append(mask)
        return super().screenshot(path, mask)


def test_successful_replay_returns_typed_outputs(tmp_path):
    result = _runner(_happy_surface(), tmp_path).run(INPUTS)
    assert result.status == "success"
    assert result.outputs == {"product_name": "Blue Top", "cart_total": "Rs. 500"}
    assert result.failure is None


def test_replay_is_deterministic_across_runs(tmp_path):
    first = _happy_surface()
    second = _happy_surface()
    _runner(first, tmp_path / "a").run(INPUTS)
    _runner(second, tmp_path / "b").run(INPUTS)
    assert first.actions == second.actions


def test_secrets_are_never_written_to_evidence(tmp_path):
    _runner(_happy_surface(), tmp_path).run(INPUTS)
    text = (tmp_path / "run-t" / "events.jsonl").read_text()
    assert "hunter2" not in text
    assert "a@b.com" not in text


def test_product_not_found_is_a_business_outcome_not_a_failure(tmp_path):
    surface = _happy_surface()
    surface.set_state(page_text="No products found")
    result = _runner(surface, tmp_path).run(INPUTS)
    assert result.status == "business_outcome"
    assert result.outcome_code == "product_not_found"
    assert result.failure is None


def test_business_outcome_is_checked_before_the_step_checkpoint(tmp_path):
    artifact = checkout_artifact()
    artifact.steps[2].expect = ConditionSpec(kind="visible_text", text="Blue Top")
    surface = _happy_surface()
    surface.set_state(page_text="No products found")
    result = _runner(surface, tmp_path, artifact=artifact).run(INPUTS)
    assert result.status == "business_outcome"
    assert result.outcome_code == "product_not_found"


def test_artifact_level_session_expiry_applies_at_every_step(tmp_path):
    surface = _happy_surface()
    surface.set_state(page_text="Login to your account")
    result = _runner(surface, tmp_path).run(INPUTS)
    assert result.status == "business_outcome"
    assert result.outcome_code == "session_expired"


def test_one_transient_retry_then_success(tmp_path):
    surface = _happy_surface()
    surface._fail_once_on = {"navigate"}
    result = _runner(surface, tmp_path).run(INPUTS)
    assert result.status == "success"
    assert [r.kind for r in result.recoveries] == ["retried"]


def test_missing_locator_is_a_hard_failure_with_debuggable_detail(tmp_path):
    surface = _happy_surface()
    surface.set_state(text_values={"Total": "Rs. 500"})
    result = _runner(surface, tmp_path).run(INPUTS)
    assert result.status == "failure"
    assert result.failure.error_code == "locator_not_found"
    assert result.failure.step_id == "read_name"
    assert result.failure.step_index == 3
    assert result.failure.screenshot_path is not None


def test_failed_success_condition_is_a_hard_failure(tmp_path):
    surface = _happy_surface()
    surface.set_state(page_text="Something else entirely")
    result = _runner(surface, tmp_path).run(INPUTS)
    assert result.status == "failure"
    assert result.failure.error_code == "success_condition_failed"


def test_missing_required_input_fails_before_the_browser_is_touched(tmp_path):
    surface = _happy_surface()
    result = _runner(surface, tmp_path).run({"product": "Blue Top"})
    assert result.status == "failure"
    assert result.failure.error_code == "invalid_inputs"
    assert surface.actions == []


def test_invalid_input_value_is_rejected(tmp_path):
    result = _runner(_happy_surface(), tmp_path).run({**INPUTS, "quantity": 0})
    assert result.status == "failure"
    assert result.failure.error_code == "invalid_inputs"


def test_policy_denial_on_navigation_is_a_hard_failure(tmp_path):
    artifact = checkout_artifact()
    artifact.steps[0].url = "https://ads.example.com/tracker"
    result = _runner(_happy_surface(), tmp_path, artifact=artifact).run(INPUTS)
    assert result.status == "failure"
    assert result.failure.error_code == "policy_origin_denied"


def test_tenant_profile_overrides_only_named_steps(tmp_path):
    profile = TenantProfile(
        tenant_id="variant_b",
        base_url="http://127.0.0.1:8000",
        locator_overrides={"read_name": loc("Item Description", role="cell")},
        condition_overrides={},
    )
    surface = FakeSurface(
        url="https://automationexercise.com/",
        page_text="Review Your Order",
        text_values={"Item Description": "Blue Top", "Total": "Rs. 500"},
    )
    result = _runner(surface, tmp_path, tenant=profile).run(INPUTS)
    assert result.status == "success"
    assert result.outputs["product_name"] == "Blue Top"
    assert ("text_of", "Total") in surface.actions


def test_handoff_never_replays_a_policy_denied_navigation(tmp_path):
    artifact = checkout_artifact()
    artifact.steps[0].url = "https://ads.example.com/tracker"
    handoff = _Handoff()

    result = _runner(_happy_surface(), tmp_path, artifact=artifact, handoff=handoff,
                     interactive=True).run(INPUTS)

    assert result.failure.error_code == "policy_origin_denied"
    assert handoff.calls == 0


def test_failure_screenshot_masks_tenant_sensitive_fill_target(tmp_path):
    artifact = checkout_artifact()
    artifact.steps[1].value_from_input = "password"
    profile = TenantProfile(
        tenant_id="variant_b",
        base_url="https://automationexercise.com",
        locator_overrides={"search": loc("Tenant Password", role="textbox")},
    )
    surface = _MaskSurface(
        page_text="Review Your Order", text_values={"Total": "Rs. 500"},
    )

    result = _runner(surface, tmp_path, artifact=artifact, tenant=profile).run(INPUTS)

    assert result.status == "failure"
    assert [spec.primary.name for spec in surface.screenshot_masks[-1]] == ["Tenant Password"]


def test_bad_output_value_is_a_structured_failure(tmp_path):
    artifact = checkout_artifact()
    artifact.outputs["product_name"] = OutputSpec(type="integer", from_step="read_name")

    result = _runner(_happy_surface(), tmp_path, artifact=artifact).run(INPUTS)

    assert result.status == "failure"
    assert result.failure.error_code == "output_conversion_failed"
    assert result.failure.screenshot_path is not None


def test_handoff_reports_the_failure_from_its_replay_attempt(tmp_path):
    artifact = checkout_artifact()
    artifact.steps[3].expect = ConditionSpec(kind="visible_text", text="Expected after handoff")
    surface = _happy_surface()
    surface.set_state(text_values={"Total": "Rs. 500"})
    handoff = _Handoff(lambda repaired: repaired.set_state(
        text_values={"Product Name": "Blue Top", "Total": "Rs. 500"},
    ))

    result = _runner(surface, tmp_path, artifact=artifact, handoff=handoff,
                     interactive=True).run(INPUTS)

    assert result.status == "failure"
    assert result.failure.error_code == "checkpoint_failed"


def test_interactive_hard_failure_offers_handoff_and_can_resume(tmp_path):
    surface = _happy_surface()
    surface.set_state(text_values={"Total": "Rs. 500"})

    def prompt(message):
        if "Take control" in message:
            surface.set_state(text_values={
                "Product Name": "Blue Top", "Total": "Rs. 500",
            })
            return "y"
        if "Operator" in message:
            return "Aryan"
        return "Found the heading manually."

    handoff = TerminalHandoff(
        evidence=EvidenceWriter(tmp_path, "run-t", set()), prompt=prompt,
    )
    result = _runner(surface, tmp_path, handoff=handoff, interactive=True).run(INPUTS)

    assert result.handoffs and result.handoffs[0].accepted
    assert result.status == "success"
    assert result.failure is None
    assert result.outputs["product_name"] == "Blue Top"


def test_non_interactive_hard_failure_never_prompts(tmp_path):
    def prompt(_message):
        raise AssertionError("a production replay must never block on an operator")

    surface = _happy_surface()
    surface.set_state(text_values={"Total": "Rs. 500"})
    handoff = TerminalHandoff(
        evidence=EvidenceWriter(tmp_path, "run-t", set()), prompt=prompt,
    )
    result = _runner(surface, tmp_path, handoff=handoff, interactive=False).run(INPUTS)

    assert result.status == "failure"
    assert result.handoffs == []


def test_handoff_receives_tenant_sensitive_masks_and_runtime_values(tmp_path):
    artifact = checkout_artifact()
    artifact.steps[1].value_from_input = "password"
    profile = TenantProfile(
        tenant_id="variant_b",
        base_url="https://automationexercise.com",
        locator_overrides={"search": loc("Tenant Password", role="textbox")},
    )
    handoff = _CapturingHandoff()
    surface = _happy_surface()
    surface.set_state(text_values={"Total": "Rs. 500"})

    result = _runner(surface, tmp_path, artifact=artifact, tenant=profile,
                     handoff=handoff, interactive=True).run(INPUTS)

    assert result.status == "failure"
    assert [mask.primary.name for mask in handoff.kwargs["masks"]] == ["Tenant Password"]
    assert handoff.kwargs["known_sensitive_values"] == {"a@b.com", "hunter2"}


def test_requires_human_handoff_receives_tenant_sensitive_context(tmp_path):
    artifact = checkout_artifact()
    artifact.steps[1].value_from_input = "password"
    artifact.steps[3].risk = "requires_human"
    profile = TenantProfile(
        tenant_id="variant_b",
        base_url="https://automationexercise.com",
        locator_overrides={"search": loc("Tenant Password", role="textbox")},
    )
    handoff = _CapturingHandoff()

    result = _runner(_happy_surface(), tmp_path, artifact=artifact, tenant=profile,
                     handoff=handoff).run(INPUTS)

    assert result.status == "business_outcome"
    assert [mask.primary.name for mask in handoff.kwargs["masks"]] == ["Tenant Password"]
    assert handoff.kwargs["known_sensitive_values"] == {"a@b.com", "hunter2"}
