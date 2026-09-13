"""Deterministic execution of a saved artifact. No model, ever."""
from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from automation.conditions import evaluate
from automation.evidence import EvidenceWriter
from automation.models import (
    CapabilityArtifact,
    FailureDetail,
    HandoffSummary,
    Locator,
    LocatorSpec,
    RecoveryRecord,
    RunResult,
    Step,
    TenantProfile,
)
from automation.policy import PolicyDenied, PolicyEngine
from automation.surface import ActionBlocked, LocatorNotFound, Surface, UnexpectedDialog

INTERSTITIAL_HINTS = ("Consent", "Accept", "Close", "Dismiss")


class _Outcome(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class _Failure(Exception):
    def __init__(self, code: str, expected: str, observed: str):
        super().__init__(code)
        self.code, self.expected, self.observed = code, expected, observed


class ReplayRunner:
    def __init__(self, artifact: CapabilityArtifact, policy: PolicyEngine,
                 evidence: EvidenceWriter, surface: Surface,
                 tenant: TenantProfile | None = None, handoff=None,
                 interactive: bool = False):
        self._artifact = artifact
        self._policy = policy
        self._evidence = evidence
        self._surface = surface
        self._tenant = tenant
        self._handoff = handoff
        self._interactive = interactive
        self._recoveries: list[RecoveryRecord] = []
        self._handoffs: list[HandoffSummary] = []
        self.run_id = f"replay-{uuid.uuid4().hex[:8]}"

    def run(self, inputs: dict[str, Any]) -> RunResult:
        self._evidence.event("run_started", run_id=self.run_id,
                             capability=self._artifact.name,
                             artifact_version=self._artifact.artifact_version,
                             tenant=self._tenant.tenant_id if self._tenant else None)
        supported = self._artifact.target.supported_versions
        running = self._tenant.product_version if self._tenant else None
        if supported and running and supported != running:
            # Drift is reported, never fatal: the artifact may well still work,
            # and a caller that blocks on a version string stops shipping.
            self._evidence.event("tenant_version_drift",
                                 artifact_supports=supported, tenant_runs=running)
        try:
            values = self._validate_inputs(inputs)
        except _Failure as exc:
            return self._fail(exc, step=None, index=-1, screenshot=False)

        self._evidence.add_sensitive_values(self._sensitive_values(values))

        outputs: dict[str, Any] = {}
        steps = self._apply_tenant(self._artifact.steps)
        masks = self._sensitive_fill_targets(steps)
        for index, step in enumerate(steps):
            try:
                self._execute(step, index, values, outputs, masks)
            except _Outcome as exc:
                return self._outcome(step, outputs, exc.code)
            except _Failure as exc:
                try:
                    resumed = self._try_handoff(step, index, exc, values, outputs, masks)
                except _Outcome as outcome:
                    return self._outcome(step, outputs, outcome.code)
                except _Failure as handoff_failure:
                    return self._fail(handoff_failure, step, index, steps=steps)
                except UnexpectedDialog as dialog:
                    failure = _Failure(
                        "unexpected_dialog", "no unmodeled browser dialog", str(dialog),
                    )
                    return self._fail(failure, step, index, steps=steps)
                if not resumed:
                    return self._fail(exc, step, index, steps=steps)
        try:
            self._check_success_condition()
        except _Failure as exc:
            return self._fail(exc, steps[-1], len(steps) - 1, steps=steps)
        except UnexpectedDialog as exc:
            failure = _Failure("unexpected_dialog", "no unmodeled browser dialog", str(exc))
            return self._fail(failure, steps[-1], len(steps) - 1, steps=steps)

        self._evidence.event("run_succeeded", outputs=outputs)
        return self._result("success", outputs)

    def _validate_inputs(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(inputs, dict):
            raise _Failure("invalid_inputs", "a dictionary matching the artifact contract",
                           f"received {type(inputs).__name__}")
        problems, values = [], {}
        for name, spec in self._artifact.inputs.items():
            if name not in inputs:
                if spec.required:
                    problems.append(f"{name}: required")
                continue
            try:
                values[name] = spec.validate_value(inputs[name])
            except ValueError as exc:
                problems.append(f"{name}: {'invalid value' if spec.sensitive else exc}")
        problems.extend(f"{name}: not an input of this capability"
                        for name in sorted(set(inputs) - set(self._artifact.inputs)))
        if problems:
            raise _Failure("invalid_inputs", "inputs matching the artifact contract",
                           "; ".join(problems))
        return values

    def _apply_tenant(self, steps: list[Step]) -> list[Step]:
        if not self._tenant:
            return steps
        out = []
        for step in steps:
            locator = self._tenant.locator_overrides.get(step.id)
            condition = self._tenant.condition_overrides.get(step.id)
            rebased = self._rebase(step.url) if step.action == "navigate" else step.url
            moved = rebased != step.url
            if locator or condition or moved:
                step = step.model_copy(update={
                    "target": locator or step.target,
                    "expect": condition or step.expect,
                    "url": rebased,
                })
                self._evidence.event("tenant_override", step_id=step.id,
                                     tenant=self._tenant.tenant_id,
                                     locator=bool(locator), condition=bool(condition),
                                     rebased_url=rebased if moved else None)
            out.append(step)
        return out

    def _rebase(self, url: str | None) -> str | None:
        """Re-point a recorded entry URL at the tenant's own origin."""
        if not self._tenant or not url:
            return url
        base, target = urlsplit(self._tenant.base_url), urlsplit(url)
        if not base.scheme or not base.netloc:
            return url
        return urlunsplit((base.scheme, base.netloc, target.path,
                           target.query, target.fragment))

    def _execute(self, step: Step, index: int, values: dict[str, Any], outputs: dict[str, Any],
                 masks: list[LocatorSpec]) -> None:
        try:
            self._execute_step(step, index, values, outputs, masks)
        except UnexpectedDialog as exc:
            raise _Failure("unexpected_dialog", "no unmodeled browser dialog", str(exc))

    def _execute_step(self, step: Step, index: int, values: dict[str, Any], outputs: dict[str, Any],
                      masks: list[LocatorSpec]) -> None:
        self._check_action_policy(step, index)
        self._evidence.event("step_started", step_id=step.id, action=step.action,
                             risk=step.risk)
        if self._policy.needs_human(step.risk):
            self._require_human(step, values, masks)
        else:
            self._act(step, values, outputs, attempt=1)
        self._check_current_url()
        self._check_business_outcomes(step)
        self._check_expectation(step)
        self._evidence.event("step_succeeded", step_id=step.id)

    def _check_action_policy(self, step: Step, index: int) -> None:
        try:
            self._policy.check_action(
                step.action, risk=step.risk, target=step.target, url=step.url,
            )
            current_url = self._surface.current_url()
            if current_url != "about:blank" or index != 0 or step.action != "navigate":
                self._policy.check_url(current_url)
            if step.action == "navigate":
                self._policy.check_url(step.url)
        except PolicyDenied as exc:
            raise _Failure(exc.code, "an allowed origin and route", exc.detail)

    def _act(self, step: Step, values: dict[str, Any], outputs: dict[str, Any],
             attempt: int) -> None:
        try:
            self._dispatch(step, values, outputs)
        except LocatorNotFound:
            if attempt == 1 and self._dismiss_interstitial(step):
                return self._act(step, values, outputs, attempt + 1)
            raise _Failure("locator_not_found",
                           f"a unique visible element for step {step.id}",
                           f"no match at {self._surface.current_url()}")
        except UnexpectedDialog as exc:
            raise _Failure("unexpected_dialog", "no unmodeled browser dialog", str(exc))
        except ActionBlocked as exc:
            if (attempt == 1 and step.action in ("click", "fill", "select")
                    and self._dismiss_interstitial(step)):
                return self._act(step, values, outputs, attempt + 1)
            raise _Failure("timeout", f"step {step.id} to complete", str(exc))
        except TimeoutError as exc:
            if attempt == 1 and step.action == "navigate":
                self._recoveries.append(RecoveryRecord(step_id=step.id, kind="retried",
                                                       detail=str(exc)))
                self._evidence.event("recovered", step_id=step.id, kind="retried")
                return self._act(step, values, outputs, attempt + 1)
            raise _Failure("timeout", f"step {step.id} to complete", str(exc))
        except PolicyDenied as exc:
            raise _Failure(exc.code, "an allowed origin and route", exc.detail)

    def _dispatch(self, step: Step, values: dict[str, Any], outputs: dict[str, Any]) -> None:
        surface, timeout = self._surface, step.timeout_ms
        if step.action == "navigate":
            surface.navigate(step.url, timeout)
        elif step.action == "click":
            surface.click(step.target, timeout)
        elif step.action == "fill":
            surface.fill(step.target, str(values[step.value_from_input]), timeout)
        elif step.action == "select":
            surface.select(step.target, str(values[step.value_from_input]), timeout)
        elif step.action == "extract":
            raw = surface.text_of(step.target, timeout)
            try:
                outputs[step.output_name] = self._coerce(step.output_name, raw)
            except ValueError as exc:
                raise _Failure("output_conversion_failed",
                               f"{step.output_name} to match its output type", str(exc))
        elif step.action == "assert" and not surface.is_visible(step.target, timeout):
            raise LocatorNotFound(step.target)

    def _coerce(self, output_name: str, raw: str) -> Any:
        kind = self._artifact.outputs[output_name].type
        if kind == "integer":
            return int("".join(char for char in raw if char.isdigit()))
        if kind == "number":
            return float("".join(char for char in raw if char.isdigit() or char == "."))
        if kind == "boolean":
            return bool(raw.strip())
        return raw

    def _dismiss_interstitial(self, step: Step) -> bool:
        for label in INTERSTITIAL_HINTS:
            spec = LocatorSpec(primary=Locator(kind="role_name", role="button", name=label))
            if self._surface.is_visible(spec, 1_000):
                try:
                    self._surface.click(spec, 2_000)
                except (LocatorNotFound, TimeoutError):
                    return False
                self._recoveries.append(RecoveryRecord(
                    step_id=step.id, kind="interstitial_dismissed", detail=label))
                self._evidence.event("recovered", step_id=step.id,
                                     kind="interstitial_dismissed", label=label)
                return True
        return False

    def _check_business_outcomes(self, step: Step) -> None:
        for outcome in [*step.business_outcomes, *self._artifact.business_outcomes]:
            if evaluate(outcome.when, self._surface):
                raise _Outcome(outcome.code)

    def _check_expectation(self, step: Step) -> None:
        if step.expect and not evaluate(step.expect, self._surface):
            raise _Failure("checkpoint_failed", _describe(step.expect),
                           f"at {self._surface.current_url()}")

    def _check_current_url(self) -> None:
        try:
            self._policy.check_url(self._surface.current_url())
        except PolicyDenied as exc:
            raise _Failure(exc.code, "an allowed origin and route", exc.detail)

    def _check_success_condition(self) -> None:
        condition = (self._tenant.success_condition_override
                     if self._tenant and self._tenant.success_condition_override
                     else self._artifact.success_condition)
        if not evaluate(condition, self._surface):
            raise _Failure("success_condition_failed", _describe(condition),
                           f"at {self._surface.current_url()}")

    def _require_human(self, step: Step, values: dict[str, Any],
                       masks: list[LocatorSpec]) -> None:
        if not self._handoff:
            raise _Failure("handoff_unavailable",
                           f"an operator for requires_human step {step.id}",
                           "no handoff channel was configured")
        record = self._handoff.request(
            run_id=self.run_id, capability=self._artifact.name, step_id=step.id,
            reason=f"step {step.id} is marked requires_human", surface=self._surface,
            masks=masks, known_sensitive_values=self._sensitive_values(values),
        )
        self._handoffs.append(record)
        if not record.accepted:
            if record.termination == "timeout":
                raise _Failure(
                    "handoff_timeout",
                    f"an operator for requires_human step {step.id}",
                    "terminal handoff timed out",
                )
            raise _Outcome("cancelled_by_human")

    def _try_handoff(self, step: Step, index: int, failure: _Failure,
                     values: dict[str, Any], outputs: dict[str, Any],
                     masks: list[LocatorSpec]) -> bool:
        if failure.code.startswith("policy_") or not (self._interactive and self._handoff):
            return False
        record = self._handoff.request(
            run_id=self.run_id, capability=self._artifact.name, step_id=step.id,
            reason=f"{failure.code}: expected {failure.expected}, observed {failure.observed}",
            surface=self._surface,
            masks=masks, known_sensitive_values=self._sensitive_values(values),
        )
        self._handoffs.append(record)
        if not record.accepted:
            if record.termination == "timeout":
                raise _Failure(
                    "handoff_timeout", "operator repair of the failed step",
                    "terminal handoff timed out",
                )
            return False
        self._check_current_url()
        self._check_business_outcomes(step)
        if step.expect is None:
            return False
        self._check_expectation(step)
        if step.action == "extract":
            return False
        self._evidence.event("resumed_after_handoff", step_id=step.id,
                             operator=record.operator)
        return True

    def _outcome(self, step: Step, outputs: dict[str, Any], code: str) -> RunResult:
        self._evidence.event("business_outcome", step_id=step.id, code=code)
        return self._result("business_outcome", outputs, outcome_code=code)

    def _fail(self, exc: _Failure, step: Step | None, index: int,
              screenshot: bool = True, steps: list[Step] | None = None) -> RunResult:
        path = None
        if screenshot:
            path = self._surface.screenshot(
                self._evidence.screenshot_path("failure"),
                mask=self._sensitive_fill_targets(steps or []),
            )
        detail = FailureDetail(
            step_id=step.id if step else "-", step_index=index,
            error_code=exc.code, expected=exc.expected, observed=exc.observed[:500],
            screenshot_path=path,
        )
        self._evidence.event("run_failed", **detail.model_dump())
        return self._result("failure", {}, failure=detail)

    def _sensitive_fill_targets(self, steps: list[Step]) -> list[LocatorSpec]:
        sensitive = self._artifact.sensitive_input_names()
        return [step.target for step in steps if step.action == "fill"
                and step.value_from_input in sensitive]

    def _sensitive_values(self, values: dict[str, Any]) -> set[str]:
        sensitive = self._artifact.sensitive_input_names()
        return {str(values[name]) for name in sensitive if str(values.get(name, ""))}

    def _result(self, status: str, outputs: dict[str, Any], **kwargs: Any) -> RunResult:
        result = RunResult(
            run_id=self.run_id, capability=self._artifact.name, status=status,
            outputs=outputs, recoveries=self._recoveries, handoffs=self._handoffs,
            evidence_dir=self._evidence.relative_path(self._evidence.run_dir), **kwargs,
        )
        result = RunResult.model_validate(self._evidence.redact(result.model_dump()))
        self._evidence.write_json("result.json", result)
        return result


def _describe(condition) -> str:
    return f"{condition.kind}({condition.pattern or condition.text or condition.expected or ''})"
