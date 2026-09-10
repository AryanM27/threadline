import pytest

from automation.evidence import EvidenceWriter
from automation.handoff import ControlState, TerminalHandoff
from tests.fakes import FakeSurface, loc


def _handoff(tmp_path, answers):
    responses = iter(answers)
    return TerminalHandoff(
        evidence=EvidenceWriter(tmp_path, "run-h", set()),
        prompt=lambda _msg: next(responses),
    )


def test_accepted_handoff_records_operator_and_transitions_control(tmp_path):
    handoff = _handoff(tmp_path, ["y", "Aryan", "Deleted the account via the UI."])
    record = handoff.request(
        run_id="r1", capability="delete_test_account", step_id="s9",
        reason="requires_human", surface=FakeSurface(
            url="https://automationexercise.com/delete_account"),
    )

    assert record.accepted is True
    assert record.operator == "Aryan"
    assert record.description == "Deleted the account via the UI."
    assert handoff.state is ControlState.AUTOMATION
    assert handoff.transitions == [
        ControlState.PAUSED, ControlState.HUMAN, ControlState.AUTOMATION,
    ]


def test_declined_handoff_returns_unaccepted_and_never_reaches_human(tmp_path):
    handoff = _handoff(tmp_path, ["n"])

    record = handoff.request(
        run_id="r1", capability="delete_test_account", step_id="s9",
        reason="requires_human", surface=FakeSurface(),
    )

    assert record.accepted is False
    assert ControlState.HUMAN not in handoff.transitions
    assert handoff.state is ControlState.AUTOMATION


def test_before_and_after_screenshots_are_captured(tmp_path):
    surface = FakeSurface()
    handoff = _handoff(tmp_path, ["y", "Aryan", "did the thing"])

    record = handoff.request(
        run_id="r1", capability="c", step_id="s1", reason="r", surface=surface,
    )

    assert record.before_screenshot in surface.screenshots
    assert record.after_screenshot in surface.screenshots
    assert record.before_screenshot != record.after_screenshot


def test_accepted_handoff_masks_before_and_after_screenshots(tmp_path):
    surface = FakeSurface()
    handoff = _handoff(tmp_path, ["y", "Aryan", "did the thing"])
    password = loc("Password", role="textbox")

    handoff.request(
        run_id="r1", capability="c", step_id="s1", reason="r", surface=surface,
        masks=[password],
    )

    assert surface.screenshot_masks == [[password], [password]]


def test_declined_handoff_masks_its_before_screenshot(tmp_path):
    surface = FakeSurface()
    handoff = _handoff(tmp_path, ["n"])
    password = loc("Password", role="textbox")

    handoff.request(
        run_id="r1", capability="c", step_id="s1", reason="r", surface=surface,
        masks=[password],
    )

    assert surface.screenshot_masks == [[password]]


def test_operator_navigation_is_recorded_while_control_is_human(tmp_path):
    surface = FakeSurface(url="https://automationexercise.com/account")

    def prompt(message):
        if message.startswith("Take control"):
            return "y"
        if message.startswith("Operator name"):
            return "Aryan"
        assert handoff.state is ControlState.HUMAN
        surface.set_state(url="https://automationexercise.com/delete_account")
        surface.set_state(url="https://automationexercise.com/account_deleted")
        return "Confirmed the deletion."

    handoff = TerminalHandoff(
        evidence=EvidenceWriter(tmp_path, "run-h", set()), prompt=prompt,
    )
    record = handoff.request(
        run_id="r1", capability="c", step_id="s1", reason="r", surface=surface,
    )

    assert record.url_trail[-1].endswith("/account_deleted")


def test_intervention_request_is_written_to_evidence_without_a11y_content(tmp_path):
    handoff = _handoff(tmp_path, ["n"])
    handoff.request(
        run_id="r1", capability="delete_test_account", step_id="s9",
        reason="requires_human", surface=FakeSurface(a11y="raw DOM secret"),
    )

    text = (tmp_path / "run-h" / "events.jsonl").read_text()
    assert "intervention_requested" in text
    assert "delete_test_account" in text
    assert "raw DOM secret" not in text


def test_handoff_sanitizes_strings_before_rendering_or_persisting(tmp_path, capsys):
    secret = "hunter2"
    surface = FakeSurface(url=f"https://automationexercise.com/{secret}?token={secret}#{secret}")

    def prompt(message):
        if message.startswith("Take control"):
            return "y"
        if message.startswith("Operator name"):
            return f"Aryan {secret}"
        surface.set_state(url=f"https://automationexercise.com/done/{secret}?token={secret}")
        return f"Used {secret}"

    handoff = TerminalHandoff(
        evidence=EvidenceWriter(tmp_path, "run-h", set()), prompt=prompt,
    )
    record = handoff.request(
        run_id="r1", capability="c", step_id="s1", reason=f"failed {secret}",
        surface=surface, known_sensitive_values={secret},
    )

    assert secret not in capsys.readouterr().out
    assert secret not in (tmp_path / "run-h" / "events.jsonl").read_text()
    assert secret not in record.operator
    assert secret not in record.description
    assert all(secret not in url and "?" not in url and "#" not in url
               for url in record.url_trail)


@pytest.mark.parametrize("failure", ["prompt", "before_screenshot", "after_screenshot"])
def test_handoff_exceptions_restore_automation_and_detach_navigation(tmp_path, failure):
    surface = FakeSurface()
    calls = 0

    def prompt(message):
        nonlocal calls
        calls += 1
        if failure == "prompt":
            raise RuntimeError(failure)
        return "y" if calls == 1 else "Aryan" if calls == 2 else "done"

    if failure.endswith("screenshot"):
        original = surface.screenshot

        def screenshot(*args, **kwargs):
            if (failure == "before_screenshot" and not surface.screenshots) or (
                failure == "after_screenshot" and surface.screenshots
            ):
                raise RuntimeError(failure)
            return original(*args, **kwargs)

        surface.screenshot = screenshot

    handoff = TerminalHandoff(
        evidence=EvidenceWriter(tmp_path, "run-h", set()), prompt=prompt,
    )
    with pytest.raises(RuntimeError, match=failure):
        handoff.request(run_id="r1", capability="c", step_id="s1", reason="r", surface=surface)

    assert handoff.state is ControlState.AUTOMATION
    assert surface._nav_callbacks == []
