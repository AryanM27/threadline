import json
from pathlib import Path

from automation.evidence import EvidenceWriter
from automation.handoff import TerminalHandoff
from automation.models import (
    CapabilityArtifact,
    ConditionSpec,
    HandoffSummary,
    OutputSpec,
    Step,
    TenantProfile,
)
from automation.policy import Policy, PolicyEngine
from automation.replay import ReplayRunner
from automation.surface import UnexpectedDialog
from tests.fakes import FakeSurface, checkout_artifact, loc

INPUTS = {"email": "a@b.com", "password": "hunter2", "product": "Blue Top", "quantity": 1}
REPO = Path(__file__).resolve().parents[1]


def test_the_legacy_base_artifact_needs_no_tenant_overrides():
    artifact = CapabilityArtifact(
        **json.loads((REPO / "evidence/artifacts/legacy_product_lookup.json").read_text()))
    tenant = TenantProfile(
        **json.loads((REPO / "config/tenants/legacy_variant.json").read_text()))
    for step in artifact.steps:
        if step.target:
            assert step.target.primary.kind != "css", (
                f"{step.id}: the base artifact must resolve on the base variant "
                "without an override")
    assert set(tenant.locator_overrides) <= {s.id for s in artifact.steps}
    assert set(tenant.condition_overrides) <= {s.id for s in artifact.steps}
    assert "dismiss_consent" not in {s.id for s in artifact.steps}


def test_the_checked_in_legacy_versions_emit_a_drift_event(tmp_path):
    artifact = CapabilityArtifact(
        **json.loads((REPO / "evidence/artifacts/legacy_product_lookup.json").read_text()))
    tenant = TenantProfile(
        **json.loads((REPO / "config/tenants/legacy_variant.json").read_text()))
    assert artifact.target.supported_versions == "4.2"
    assert tenant.product_version == "4.3"

    surface = FakeSurface(
        url="about:blank", visible=["Item Lookup", "Item Description"],
        text_values={"Item Description": "Blue Top", "Amount Due": "$5"},
    )
    _runner(surface, tmp_path, artifact=artifact, tenant=tenant,
            policy=_engine_allowing_loopback()).run({"product": "Blue Top"})
    events = [json.loads(line) for line
              in (tmp_path / "run-t" / "events.jsonl").read_text().splitlines()]

    assert any(e["type"] == "tenant_version_drift" for e in events)


def _engine():
    return PolicyEngine(Policy(
        allowed_origins=[{"scheme": "https", "host": "automationexercise.com"}],
        denied_route_patterns=["/payment*"],
        allowed_actions=["navigate", "click", "fill", "select", "extract", "assert"],
    ))


def _engine_allowing_loopback():
    return PolicyEngine(Policy(
        allowed_origins=[{"scheme": "https", "host": "automationexercise.com"},
                         {"scheme": "http", "host": "127.0.0.1", "port": 8001}],
        denied_route_patterns=["/payment*"],
        allowed_actions=["navigate", "click", "fill", "select", "extract", "assert"],
    ))


def _runner(surface, tmp_path, artifact=None, policy=None, **kw):
    artifact = artifact or checkout_artifact()
    return ReplayRunner(
        artifact=artifact,
        policy=policy or _engine(),
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


def test_serialized_result_uses_relative_evidence_paths_inside_the_repository(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _runner(_happy_surface(), tmp_path).run(INPUTS)
    result_json = (tmp_path / "run-t" / "result.json").read_text()

    assert str(tmp_path) not in result_json
    assert not Path(json.loads(result_json)["evidence_dir"]).is_absolute()


def test_a_version_mismatch_is_recorded_but_does_not_block_the_run(tmp_path):
    artifact = checkout_artifact(target={"vendor_product": "automationexercise",
                                         "base_url": "https://automationexercise.com",
                                         "supported_versions": "4.1"})
    tenant = TenantProfile(tenant_id="t", base_url="https://automationexercise.com",
                           product_version="4.2")
    result = _runner(_happy_surface(), tmp_path, artifact=artifact,
                     tenant=tenant).run(INPUTS)
    assert result.status == "success"
    events = [json.loads(line) for line
              in (tmp_path / "run-t" / "events.jsonl").read_text().splitlines()]
    drift = next(e for e in events if e["type"] == "tenant_version_drift")
    assert drift["artifact_supports"] == "4.1" and drift["tenant_runs"] == "4.2"


def test_matching_versions_emit_no_drift_event(tmp_path):
    artifact = checkout_artifact(target={"vendor_product": "automationexercise",
                                         "base_url": "https://automationexercise.com",
                                         "supported_versions": "4.2"})
    tenant = TenantProfile(tenant_id="t", base_url="https://automationexercise.com",
                           product_version="4.2")
    _runner(_happy_surface(), tmp_path, artifact=artifact, tenant=tenant).run(INPUTS)
    events = [json.loads(line) for line
              in (tmp_path / "run-t" / "events.jsonl").read_text().splitlines()]
    assert not any(e["type"] == "tenant_version_drift" for e in events)


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


def test_sensitive_value_in_output_is_redacted_from_result_and_evidence(tmp_path):
    surface = _happy_surface()
    surface.set_state(text_values={"Product Name": "hunter2", "Total": "Rs. 500"})

    result = _runner(surface, tmp_path).run(INPUTS)

    assert result.outputs["product_name"] == "[REDACTED]"
    assert "hunter2" not in (tmp_path / "run-t" / "events.jsonl").read_text()
    assert "hunter2" not in (tmp_path / "run-t" / "result.json").read_text()


def test_one_character_secret_redacts_user_output_without_corrupting_status(tmp_path):
    inputs = {**INPUTS, "password": "s"}
    surface = _happy_surface()
    surface.set_state(text_values={"Product Name": "s", "Total": "Rs. 500"})

    result = _runner(surface, tmp_path).run(inputs)

    assert result.status == "success"
    assert result.outputs["product_name"] == "[REDACTED]"


def test_sensitive_value_in_failure_url_is_redacted_from_result_and_evidence(tmp_path):
    class LeakingUrlSurface(FakeSurface):
        def click(self, spec, timeout_ms):
            super().click(spec, timeout_ms)
            if spec.primary.name == "Search":
                self.set_state(url="https://automationexercise.com/hunter2")

    surface = LeakingUrlSurface(page_text="Review Your Order", text_values={"Total": "Rs. 500"})

    result = _runner(surface, tmp_path).run(INPUTS)

    assert "hunter2" not in result.failure.observed
    assert "hunter2" not in (tmp_path / "run-t" / "events.jsonl").read_text()
    assert "hunter2" not in (tmp_path / "run-t" / "result.json").read_text()


def test_sensitive_value_in_retry_detail_is_redacted_from_result_and_evidence(tmp_path):
    class SecretTimeoutSurface(FakeSurface):
        def __init__(self):
            super().__init__(page_text="Review Your Order",
                             text_values={"Product Name": "Blue Top", "Total": "Rs. 500"})
            self._timed_out = False

        def navigate(self, url, timeout_ms):
            if not self._timed_out:
                self._timed_out = True
                raise TimeoutError("retry leaked hunter2")
            super().navigate(url, timeout_ms)

    result = _runner(SecretTimeoutSurface(), tmp_path).run(INPUTS)

    assert result.recoveries[0].detail == "retry leaked [REDACTED]"
    assert "hunter2" not in (tmp_path / "run-t" / "result.json").read_text()


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


def test_click_timeout_is_not_retried(tmp_path):
    class CountingSurface(FakeSurface):
        def __init__(self):
            super().__init__(page_text="Review Your Order",
                             text_values={"Product Name": "Blue Top", "Total": "Rs. 500"})
            self.click_attempts = 0

        def click(self, spec, timeout_ms):
            self.click_attempts += 1
            raise TimeoutError("click outcome is unknown")

    surface = CountingSurface()

    result = _runner(surface, tmp_path).run(INPUTS)

    assert result.status == "failure"
    assert result.failure.error_code == "timeout"
    assert surface.click_attempts == 1
    assert result.recoveries == []


def test_a_blocked_click_is_recovered_by_dismissing_the_interstitial(tmp_path):
    surface = FakeSurface(
        url="https://automationexercise.com/",
        page_text="Review Your Order",
        visible=["Accept"],
        text_values={"Product Name": "Blue Top", "Total": "Rs. 500"},
        block_once_on=["click"],
    )

    result = _runner(surface, tmp_path).run(INPUTS)

    assert result.status == "success"
    assert [r.kind for r in result.recoveries] == ["interstitial_dismissed"]
    assert ("click", "Accept") in surface.actions
    assert surface.actions.count(("click", "Search")) == 1


def test_a_blocked_click_with_no_interstitial_is_a_hard_failure(tmp_path):
    surface = FakeSurface(url="https://automationexercise.com/", block_once_on=["click"])

    result = _runner(surface, tmp_path).run(INPUTS)

    assert result.status == "failure"
    assert result.failure.error_code == "timeout"
    assert result.recoveries == []


def test_a_failed_interstitial_dismissal_stays_a_structured_failure(tmp_path):
    class DismissalFailsSurface(FakeSurface):
        def click(self, spec, timeout_ms):
            if spec.primary.name == "Accept":
                raise TimeoutError("dismissal timed out")
            super().click(spec, timeout_ms)

    surface = DismissalFailsSurface(
        url="https://automationexercise.com/", visible=["Accept"], block_once_on=["click"],
    )

    result = _runner(surface, tmp_path).run(INPUTS)

    assert result.status == "failure"
    assert result.failure.error_code == "timeout"
    assert result.recoveries == []


def test_a_timed_out_click_is_never_retried_even_with_an_interstitial_visible(tmp_path):
    surface = FakeSurface(
        url="https://automationexercise.com/", visible=["Accept"], fail_once_on=["click"],
    )

    result = _runner(surface, tmp_path).run(INPUTS)

    assert result.status == "failure"
    assert result.failure.error_code == "timeout"
    assert ("click", "Accept") not in surface.actions


def test_unexpected_dialog_is_a_structured_hard_failure(tmp_path):
    class DialogSurface(FakeSurface):
        def click(self, spec, timeout_ms):
            raise UnexpectedDialog("Are you sure hunter2?")

    result = _runner(DialogSurface(), tmp_path).run(INPUTS)

    assert result.status == "failure"
    assert result.failure.error_code == "unexpected_dialog"
    assert "hunter2" not in result.failure.observed


def test_unexpected_dialog_during_url_preflight_is_a_structured_failure(tmp_path):
    class DialogSurface(FakeSurface):
        def current_url(self):
            raise UnexpectedDialog("pending")

    result = _runner(DialogSurface(), tmp_path).run(INPUTS)

    assert result.status == "failure"
    assert result.failure.error_code == "unexpected_dialog"


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


def test_off_origin_current_url_blocks_navigation_before_browser_action(tmp_path):
    surface = _happy_surface()
    surface.set_state(url="https://ads.example.com/landing")

    result = _runner(surface, tmp_path).run(INPUTS)

    assert result.status == "failure"
    assert result.failure.error_code == "policy_origin_denied"
    assert surface.actions == []


def test_about_blank_does_not_exempt_a_non_navigation_first_step(tmp_path):
    artifact = checkout_artifact()
    artifact.steps[0] = Step(id="go_products", action="click", target=loc("Products"))
    surface = _happy_surface()
    surface.set_state(url="about:blank")

    result = _runner(surface, tmp_path, artifact=artifact).run(INPUTS)

    assert result.status == "failure"
    assert result.failure.error_code == "policy_origin_denied"
    assert surface.actions == []


def test_about_blank_does_not_exempt_a_later_navigation_step(tmp_path):
    artifact = checkout_artifact()
    artifact.steps[0].expect = None
    artifact.steps[1] = Step(
        id="search", action="navigate", url="https://automationexercise.com/products",
    )

    class BlankingSurface(FakeSurface):
        def __init__(self):
            super().__init__(url="about:blank")
            self._blank_after_current_url = False

        def current_url(self):
            url = super().current_url()
            if self._blank_after_current_url:
                self.set_state(url="about:blank")
                self._blank_after_current_url = False
            return url

        def navigate(self, url, timeout_ms):
            super().navigate(url, timeout_ms)
            self._blank_after_current_url = True

    surface = BlankingSurface()

    result = _runner(surface, tmp_path, artifact=artifact).run(INPUTS)

    assert result.status == "failure"
    assert result.failure.error_code == "policy_origin_denied"
    assert surface.actions == [("navigate", "https://automationexercise.com/products")]


def test_off_origin_post_action_url_preempts_business_outcome(tmp_path):
    class RedirectingSurface(FakeSurface):
        def click(self, spec, timeout_ms):
            super().click(spec, timeout_ms)
            if spec.primary.name == "Search":
                self.set_state(
                    url="https://ads.example.com/landing",
                    page_text="No products found",
                )

    result = _runner(RedirectingSurface(), tmp_path).run(INPUTS)

    assert result.status == "failure"
    assert result.failure.error_code == "policy_origin_denied"
    assert result.outcome_code is None


def test_tenant_profile_overrides_only_named_steps(tmp_path):
    profile = TenantProfile(
        tenant_id="variant_b",
        base_url="https://automationexercise.com",
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


def test_tenant_profile_can_override_the_terminal_success_condition(tmp_path):
    profile = TenantProfile(
        tenant_id="variant_b",
        base_url="https://automationexercise.com",
        success_condition_override=ConditionSpec(kind="visible_text", text="Variant complete"),
    )
    surface = FakeSurface(
        url="https://automationexercise.com/",
        page_text="Variant complete",
        text_values={"Product Name": "Blue Top", "Total": "Rs. 500"},
    )

    assert _runner(surface, tmp_path, tenant=profile).run(INPUTS).status == "success"


def test_a_tenant_profile_rebases_navigation_onto_its_own_origin(tmp_path):
    surface = FakeSurface(url="about:blank", page_text="Review Your Order",
                          text_values={"Product Name": "Blue Top", "Total": "Rs. 500"})
    tenant = TenantProfile(tenant_id="variant_b", base_url="http://127.0.0.1:8001")
    _runner(surface, tmp_path, tenant=tenant,
            policy=_engine_allowing_loopback()).run(INPUTS)
    assert ("navigate", "http://127.0.0.1:8001/products") in surface.actions


def test_rebasing_still_has_to_satisfy_policy(tmp_path):
    surface = FakeSurface(url="about:blank")
    tenant = TenantProfile(tenant_id="rogue", base_url="https://evil.example.com")
    result = _runner(surface, tmp_path, tenant=tenant).run(INPUTS)
    assert result.status == "failure"
    assert result.failure.error_code == "policy_origin_denied"
    assert ("navigate", "https://evil.example.com/products") not in surface.actions


def test_no_tenant_leaves_navigation_untouched(tmp_path):
    surface = _happy_surface()
    _runner(surface, tmp_path).run(INPUTS)
    assert ("navigate", "https://automationexercise.com/products") in surface.actions


def test_handoff_never_replays_a_policy_denied_navigation(tmp_path):
    artifact = checkout_artifact()
    artifact.steps[0].url = "https://ads.example.com/tracker"
    handoff = _Handoff()

    result = _runner(_happy_surface(), tmp_path, artifact=artifact, handoff=handoff,
                     interactive=True).run(INPUTS)

    assert result.failure.error_code == "policy_origin_denied"
    assert handoff.calls == 0


def test_safe_delete_account_step_is_rejected_before_click(tmp_path):
    artifact = checkout_artifact()
    artifact.steps[0] = Step(
        id="go_products", action="click", target=loc("Delete Account", role="link"),
    )
    surface = _happy_surface()

    result = _runner(surface, tmp_path, artifact=artifact).run(INPUTS)

    assert result.status == "failure"
    assert result.failure.error_code == "policy_human_required"
    assert ("click", "Delete Account") not in surface.actions


def test_safe_delete_account_navigation_is_rejected_before_navigation(tmp_path):
    artifact = checkout_artifact()
    artifact.steps[0] = Step(
        id="go_delete", action="navigate",
        url="https://automationexercise.com/delete_account",
    )
    surface = _happy_surface()

    result = _runner(surface, tmp_path, artifact=artifact).run(INPUTS)

    assert result.status == "failure"
    assert result.failure.error_code == "policy_human_required"
    assert ("navigate", "https://automationexercise.com/delete_account") not in surface.actions


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
    assert result.status == "failure"
    assert result.failure.error_code == "locator_not_found"
    assert "product_name" not in result.outputs


def test_hard_failure_resume_verifies_checkpoint_without_repeating_click(tmp_path):
    artifact = checkout_artifact()
    artifact.steps[2].expect = ConditionSpec(kind="visible_text", text="Search repaired")

    class FailingClickSurface(FakeSurface):
        def __init__(self):
            super().__init__(page_text="Review Your Order",
                             text_values={"Product Name": "Blue Top", "Total": "Rs. 500"})
            self.search_attempts = 0

        def click(self, spec, timeout_ms):
            if spec.primary.name == "Search":
                self.search_attempts += 1
                raise TimeoutError("click outcome is unknown")
            super().click(spec, timeout_ms)

    surface = FailingClickSurface()
    handoff = _Handoff(lambda repaired: repaired.set_state(
        page_text="Search repaired Review Your Order",
    ))

    result = _runner(surface, tmp_path, artifact=artifact, handoff=handoff,
                     interactive=True).run(INPUTS)

    assert result.status == "success"
    assert surface.search_attempts == 1


def test_unexpected_dialog_after_handoff_is_a_structured_failure(tmp_path):
    class DialogAfterHandoffSurface(FakeSurface):
        dialog_pending = False

        def click(self, spec, timeout_ms):
            if spec.primary.name == "Search":
                raise TimeoutError("click outcome is unknown")
            super().click(spec, timeout_ms)

        def current_url(self):
            if self.dialog_pending:
                raise UnexpectedDialog("after handoff")
            return super().current_url()

    surface = DialogAfterHandoffSurface(
        page_text="Review Your Order",
        text_values={"Product Name": "Blue Top", "Total": "Rs. 500"},
    )
    handoff = _Handoff(lambda repaired: setattr(repaired, "dialog_pending", True))

    result = _runner(surface, tmp_path, handoff=handoff, interactive=True).run(INPUTS)

    assert result.status == "failure"
    assert result.failure.error_code == "unexpected_dialog"


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


def test_requires_human_timeout_returns_structured_failure(tmp_path):
    from threading import Event

    artifact = checkout_artifact()
    artifact.steps[3].risk = "requires_human"
    blocked = Event()
    handoff = TerminalHandoff(
        evidence=EvidenceWriter(tmp_path, "run-h", set()),
        prompt=lambda _message: blocked.wait(),
        timeout_seconds=0.01,
    )

    result = _runner(
        _happy_surface(), tmp_path, artifact=artifact, handoff=handoff,
    ).run(INPUTS)

    assert result.status == "failure"
    assert result.failure.error_code == "handoff_timeout"
