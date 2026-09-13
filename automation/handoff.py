"""Control transfer on the same live session."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from queue import Empty, Queue
from threading import Thread

from pydantic import BaseModel, ConfigDict

from automation.evidence import EvidenceWriter
from automation.models import HandoffSummary, LocatorSpec
from automation.surface import Surface


class ControlState(str, Enum):
    AUTOMATION = "AUTOMATION"
    PAUSED = "PAUSED"
    HUMAN = "HUMAN"


class InterventionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    capability: str
    step_id: str
    reason: str
    url: str
    observed: str
    before_screenshot: str


class _PromptTimeout(Exception):
    pass


class TerminalHandoff:
    def __init__(self, evidence: EvidenceWriter, prompt=input,
                 timeout_seconds: float = 300):
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._evidence = evidence
        self._prompt = prompt
        self._timeout_seconds = timeout_seconds
        self.state = ControlState.AUTOMATION
        self.transitions: list[ControlState] = []

    def _go(self, state: ControlState) -> None:
        self.state = state
        self.transitions.append(state)
        self._evidence.event("control_state", state=state.value)

    def request(self, run_id: str, capability: str, step_id: str, reason: str,
                surface: Surface, masks: list[LocatorSpec] | None = None,
                known_sensitive_values: set[str] | None = None) -> HandoffSummary:
        sensitive = {value for value in known_sensitive_values or set() if value}
        unsubscribe = None
        before = None
        operator = ""
        try:
            self._go(ControlState.PAUSED)
            observation = surface.observe()
            before = surface.screenshot(self._evidence.screenshot_path("handoff-before"), mask=masks)
            request = InterventionRequest(
                run_id=run_id, capability=capability, step_id=step_id,
                reason=_redact_text(reason, sensitive),
                url=_safe_url(observation.url, sensitive), observed=observation.a11y[:1_000],
                before_screenshot=before,
            )
            self._evidence.event(
                "intervention_requested", **request.model_dump(exclude={"observed"}),
            )
            self._render(request)

            if not str(self._ask("Take control of the live session? [y/N]: ")).strip().lower().startswith("y"):
                self._evidence.event("intervention_declined", step_id=step_id)
                return HandoffSummary(
                    operator="", accepted=False, termination="declined",
                    before_screenshot=before,
                )

            operator = _redact_text(
                self._ask("Operator name (do not include credentials): "), sensitive,
            ).strip()
            trail = [request.url]
            unsubscribe = surface.on_navigation(
                lambda url: trail.append(_safe_url(url, sensitive)),
            )
            self._go(ControlState.HUMAN)
            started = datetime.now(timezone.utc).isoformat()
            description = _redact_text(self._ask(
                "Take the browser now. Do not include credentials in your description. "
                "When finished, type a short description of what you did and press Enter: ",
            ), sensitive).strip()
            after = surface.screenshot(self._evidence.screenshot_path("handoff-after"), mask=masks)

            record = HandoffSummary(
                operator=operator, accepted=True, description=description,
                url_trail=trail, before_screenshot=before, after_screenshot=after,
            )
            self._evidence.event(
                "intervention_completed", operator=operator, description=description,
                url_trail=trail, started_at=started,
                ended_at=datetime.now(timezone.utc).isoformat(),
            )
            return record
        except _PromptTimeout:
            self._evidence.event(
                "intervention_terminated", step_id=step_id, reason="timeout",
            )
            return HandoffSummary(
                operator=operator, accepted=False, termination="timeout",
                before_screenshot=before,
            )
        except (EOFError, KeyboardInterrupt):
            self._evidence.event(
                "intervention_terminated", step_id=step_id, reason="interrupted",
            )
            return HandoffSummary(
                operator=operator, accepted=False, termination="interrupted",
                before_screenshot=before,
            )
        finally:
            try:
                if unsubscribe:
                    unsubscribe()
            finally:
                if self.state is not ControlState.AUTOMATION:
                    self._go(ControlState.AUTOMATION)

    def _ask(self, message: str):
        result = Queue(maxsize=1)

        def ask() -> None:
            try:
                result.put((True, self._prompt(message)))
            except BaseException as exc:
                result.put((False, exc))

        # A timed-out terminal read cannot be cancelled portably; daemonizing
        # keeps a one-shot CLI exit bounded without adding a terminal UI dependency.
        Thread(target=ask, daemon=True).start()
        try:
            ok, value = result.get(timeout=self._timeout_seconds)
        except Empty as exc:
            raise _PromptTimeout from exc
        if not ok:
            raise value
        return value

    def _render(self, request: InterventionRequest) -> None:
        print("\n" + "=" * 68)
        print("  INTERVENTION REQUESTED")
        print("=" * 68)
        print(f"  capability : {request.capability}")
        print(f"  step       : {request.step_id}")
        print(f"  reason     : {request.reason}")
        print(f"  url        : {request.url}")
        print(f"  screenshot : {request.before_screenshot}")
        print("=" * 68)


def _redact_text(value: object, sensitive: set[str]) -> str:
    text = str(value)
    for secret in sorted(sensitive, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    return text


def _safe_url(url: str, sensitive: set[str]) -> str:
    return _redact_text(url.split("#", 1)[0].split("?", 1)[0], sensitive)
