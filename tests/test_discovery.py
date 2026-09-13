import json
import re

import pytest

import automation.discovery as discovery
from automation.discovery import ArtifactRecorder, DiscoveryRunner, TOOLS
from automation.evidence import EvidenceWriter
from automation.handoff import ControlState, TerminalHandoff
from automation.models import InputSpec
from automation.policy import Policy, PolicyEngine
from automation.surface import LocatorNotFound
from tests.fakes import FakeSurface


class ScriptedClient:
    """Stands in for anthropic.Anthropic. Returns queued tool-use turns."""

    def __init__(self, turns):
        self._turns = list(turns)
        self.sent = []
        self.messages = self

    def create(self, **kwargs):
        self.sent.append(kwargs)
        return self._turns.pop(0)


class Turn:
    def __init__(self, *blocks, stop_reason="tool_use"):
        self.content = list(blocks)
        self.stop_reason = stop_reason


class ToolUse:
    type = "tool_use"

    def __init__(self, name, input, id="tu-1"):
        self.name, self.input, self.id = name, input, id


def _inputs():
    return {
        "product": InputSpec(type="string"),
        "password": InputSpec(type="string", sensitive=True),
    }


def _engine():
    return PolicyEngine(Policy(
        allowed_origins=[{"scheme": "https", "host": "automationexercise.com"}],
        denied_route_patterns=["/payment*"],
        allowed_actions=["navigate", "click", "fill", "select", "extract", "assert"],
    ))


def _runner(client, surface, tmp_path, **kwargs):
    return DiscoveryRunner(
        client=client, surface=surface, policy=_engine(),
        evidence=EvidenceWriter(tmp_path, "run-d", {"password"}),
        goal="Search for a product and read its name.",
        capability_name="demo", description=kwargs.pop("description", "Demo capability."),
        inputs=_inputs(), model_id="claude-opus-5", max_turns=10, **kwargs,
    )


def test_a_recorded_navigation_carries_a_url_checkpoint_for_where_it_landed(tmp_path):
    client = ScriptedClient([
        Turn(ToolUse("navigate", {"url": "https://automationexercise.com/products?x=1#f"})),
        Turn(ToolUse("complete", {"kind": "visible_text", "text": "done"})),
    ])
    artifact = _runner(client, FakeSurface(page_text="done"), tmp_path).run()
    expect = artifact.steps[0].expect
    assert expect.kind == "url_matches"
    assert re.search(expect.pattern, "https://automationexercise.com/products")
    assert re.search(expect.pattern, "https://automationexercise.com/products?y=2")
    assert not re.search(expect.pattern, "https://automationexercise.com/products/9")
    assert "x=1" not in expect.pattern


def test_an_explicit_checkpoint_replaces_the_automatic_one(tmp_path):
    client = ScriptedClient([
        Turn(ToolUse("navigate", {"url": "https://automationexercise.com/products"})),
        Turn(ToolUse("checkpoint", {"kind": "visible_text", "text": "All Products"})),
        Turn(ToolUse("complete", {"kind": "visible_text", "text": "All Products"})),
    ])
    artifact = _runner(client, FakeSurface(page_text="All Products"), tmp_path).run()
    assert artifact.steps[0].expect.kind == "visible_text"


def test_the_system_prompt_requires_checkpoints_after_transitions():
    assert "checkpoint" in discovery.SYSTEM_PROMPT


def test_successful_discovery_produces_a_replayable_artifact(tmp_path):
    client = ScriptedClient([
        Turn(ToolUse("navigate", {"url": "https://automationexercise.com/products"})),
        Turn(ToolUse("fill", {"role": "textbox", "name": "Search Product",
                              "value_from_input": "product",
                              "rationale": "Labelled search box."})),
        Turn(ToolUse("extract", {"role": "heading", "name": "Blue Top",
                                 "output_name": "product_name",
                                 "output_type": "string",
                                 "rationale": "Product title heading."})),
        Turn(ToolUse("complete", {"kind": "visible_text", "text": "Blue Top"})),
    ])
    surface = FakeSurface(page_text="Blue Top", text_values={"Blue Top": "Blue Top"})
    runner = _runner(client, surface, tmp_path)
    runner.set_runtime_values({"product": "Blue Top"})
    artifact = runner.run()

    assert artifact is not None
    assert [step.action for step in artifact.steps] == ["navigate", "fill", "extract"]
    assert artifact.steps[1].value_from_input == "product"
    assert artifact.outputs["product_name"].from_step == artifact.steps[2].id
    assert artifact.provenance == "discovered"
    assert artifact.model_id == "claude-opus-5"


def test_secret_values_never_enter_the_artifact_or_the_prompt(tmp_path):
    client = ScriptedClient([
        Turn(ToolUse("fill", {"role": "textbox", "name": "Password",
                              "value_from_input": "password",
                              "rationale": "Labelled password field."})),
        Turn(ToolUse("complete", {"kind": "visible_text", "text": "Logged in"})),
    ])
    surface = FakeSurface(page_text="Logged in")
    runner = _runner(client, surface, tmp_path)
    runner.set_runtime_values({"password": "hunter2", "product": "Blue Top"})
    artifact = runner.run()

    assert artifact.steps[0].value_from_input == "password"
    assert "hunter2" not in artifact.model_dump_json()
    assert "hunter2" not in str(client.sent)


def test_policy_denied_navigation_is_reported_to_the_model_not_executed(tmp_path):
    client = ScriptedClient([
        Turn(ToolUse("navigate", {"url": "https://ads.example.com/x"})),
        Turn(ToolUse("complete", {"kind": "visible_text", "text": "done"})),
    ])
    surface = FakeSurface(page_text="done")
    _runner(client, surface, tmp_path).run()
    assert ("navigate", "https://ads.example.com/x") not in surface.actions


def test_delete_account_click_is_never_executed_by_discovery(tmp_path):
    client = ScriptedClient([
        Turn(ToolUse("click", {
            "role": "link", "name": "Delete Account",
            "rationale": "Visible account deletion link.",
        })),
        Turn(ToolUse("escalate", {"reason": "Deletion requires a human."})),
    ])
    surface = FakeSurface()

    assert _runner(client, surface, tmp_path).run() is None
    assert ("click", "Delete Account") not in surface.actions


def test_partial_delete_click_is_never_executed_by_discovery(tmp_path):
    client = ScriptedClient([
        Turn(ToolUse("click", {
            "role": "button", "name": "Delete", "rationale": "Visible delete control.",
        })),
        Turn(ToolUse("escalate", {"reason": "Deletion requires a human."})),
    ])
    surface = FakeSurface()

    assert _runner(client, surface, tmp_path).run() is None
    assert ("click", "Delete") not in surface.actions


def test_delete_account_navigation_is_never_executed_by_discovery(tmp_path):
    url = "https://automationexercise.com/delete_account"
    client = ScriptedClient([
        Turn(ToolUse("navigate", {"url": url})),
        Turn(ToolUse("escalate", {"reason": "Deletion requires a human."})),
    ])
    surface = FakeSurface(url="about:blank")

    assert _runner(client, surface, tmp_path).run() is None
    assert ("navigate", url) not in surface.actions


def test_discovered_description_redacts_known_secret_without_changing_provenance(tmp_path):
    client = ScriptedClient([
        Turn(ToolUse("navigate", {"url": "https://automationexercise.com/products"})),
        Turn(ToolUse("complete", {"kind": "visible_text", "text": "done"})),
    ])
    runner = _runner(
        client, FakeSurface(page_text="done"), tmp_path,
        description="Use password hunter2 to search.",
    )
    runner.set_runtime_values({"password": "hunter2"})

    artifact = runner.run()

    assert artifact.description == "Use password [REDACTED] to search."
    assert artifact.provenance == "discovered"


def test_initial_navigation_from_about_blank_is_allowed(tmp_path):
    client = ScriptedClient([
        Turn(ToolUse("navigate", {"url": "https://automationexercise.com/products"})),
        Turn(ToolUse("complete", {"kind": "visible_text", "text": "done"})),
    ])
    surface = FakeSurface(url="about:blank", page_text="done")

    artifact = _runner(client, surface, tmp_path).run()

    assert artifact is not None
    assert artifact.steps[0].url == "https://automationexercise.com/products"


def test_initial_observation_from_about_blank_does_not_stop_discovery(tmp_path):
    client = ScriptedClient([
        Turn(ToolUse("observe", {})),
        Turn(ToolUse("navigate", {"url": "https://automationexercise.com/products"})),
        Turn(ToolUse("complete", {"kind": "visible_text", "text": "done"})),
    ])

    artifact = _runner(client, FakeSurface(url="about:blank", page_text="done"), tmp_path).run()

    assert artifact is not None
    assert artifact.steps[0].url == "https://automationexercise.com/products"


def test_initial_prompt_names_the_available_runtime_inputs(tmp_path):
    client = ScriptedClient([
        Turn(ToolUse("navigate", {"url": "https://automationexercise.com/products"})),
        Turn(ToolUse("complete", {"kind": "visible_text", "text": "done"})),
    ])

    _runner(client, FakeSurface(page_text="done"), tmp_path).run()

    assert "Available runtime input names: password, product." in client.sent[0]["messages"][0]["content"]


def test_initial_prompt_names_the_configured_starting_url(tmp_path):
    client = ScriptedClient([Turn(ToolUse("escalate", {"reason": "Test stop."}))])

    _runner(
        client, FakeSurface(), tmp_path,
        base_url="https://tenant.example.test/products",
    ).run()

    assert "Allowed starting URL: https://tenant.example.test/products." in (
        client.sent[0]["messages"][0]["content"]
    )


def test_explicit_discovery_run_id_is_written_to_artifact_and_start_event(tmp_path):
    client = ScriptedClient([
        Turn(ToolUse("navigate", {"url": "https://automationexercise.com/products"})),
        Turn(ToolUse("complete", {"kind": "visible_text", "text": "done"})),
    ])
    artifact = _runner(client, FakeSurface(page_text="done"), tmp_path,
                       run_id="discovery-shared").run()

    first_event = json.loads((tmp_path / "run-d" / "events.jsonl").read_text().splitlines()[0])
    assert artifact.discovery_run_id == "discovery-shared"
    assert first_event["type"] == "discovery_started"
    assert first_event["run_id"] == "discovery-shared"


def test_only_successful_actions_are_recorded(tmp_path):
    class MissingOnceSurface(FakeSurface):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._missing = True

        def click(self, spec, timeout_ms):
            if self._missing:
                self._missing = False
                raise LocatorNotFound(spec)
            super().click(spec, timeout_ms)

    client = ScriptedClient([
        Turn(ToolUse("click", {"role": "button", "name": "Ghost",
                               "rationale": "Guessing."})),
        Turn(ToolUse("click", {"role": "button", "name": "Search",
                               "rationale": "Labelled search button."})),
        Turn(ToolUse("complete", {"kind": "visible_text", "text": "Results"})),
    ])
    surface = MissingOnceSurface(page_text="Results")
    artifact = _runner(client, surface, tmp_path).run()
    assert len(artifact.steps) == 1
    assert artifact.steps[0].target.primary.name == "Search"


def test_turn_budget_stops_the_loop(tmp_path):
    client = ScriptedClient([Turn(ToolUse("observe", {})) for _ in range(10)])
    assert _runner(client, FakeSurface(), tmp_path).run() is None


def test_escalate_ends_discovery_without_an_artifact(tmp_path):
    client = ScriptedClient([Turn(ToolUse("escalate", {"reason": "Cannot find the form."}))])
    assert _runner(client, FakeSurface(), tmp_path).run() is None


def test_accepted_discovery_escalation_resumes_the_same_session(tmp_path):
    client = ScriptedClient([
        Turn(ToolUse("navigate", {"url": "https://automationexercise.com/products"})),
        Turn(ToolUse("escalate", {"reason": "A human must clear the blocker."})),
        Turn(ToolUse("complete", {"kind": "visible_text", "text": "done"})),
    ])
    surface = FakeSurface(page_text="done")
    evidence = EvidenceWriter(tmp_path, "run-d", {"password"})
    answers = iter(["y", "Aryan", "Cleared the blocker."])
    handoff = TerminalHandoff(evidence, prompt=lambda _message: next(answers))
    runner = DiscoveryRunner(
        client=client, surface=surface, policy=_engine(), evidence=evidence,
        goal="Search for a product and read its name.", capability_name="demo",
        description="Demo capability.", inputs=_inputs(), model_id="claude-opus-5",
        max_turns=10, handoff=handoff,
    )

    artifact = runner.run()

    assert artifact is not None
    assert artifact.steps[0].action == "navigate"
    assert handoff.transitions == [
        ControlState.PAUSED, ControlState.HUMAN, ControlState.AUTOMATION,
    ]
    assert surface.actions == [("navigate", "https://automationexercise.com/products")]


def test_tool_schemas_do_not_expose_a_raw_value_parameter(tmp_path):
    for tool in TOOLS:
        assert "value" not in tool["input_schema"]["properties"]


def test_sensitive_page_data_and_escalation_are_sanitized_before_model_or_evidence(tmp_path):
    client = ScriptedClient([
        Turn(ToolUse("observe", {})),
        Turn(ToolUse("extract", {"role": "heading", "name": "Secret Heading",
                                 "output_name": "result", "output_type": "string",
                                 "rationale": "Visible heading."})),
        Turn(ToolUse("escalate", {"reason": "hunter2 blocked the flow"})),
    ])
    surface = FakeSurface(
        url="https://automationexercise.com/?leak=hunter2#hunter2",
        title="hunter2 title", a11y="hunter2 accessibility tree",
        text_values={"Secret Heading": "hunter2"},
    )
    runner = _runner(client, surface, tmp_path)
    runner.set_runtime_values({"password": "hunter2"})
    runner._goal = "hunter2 goal"

    assert runner.run() is None
    assert "hunter2" not in str(client.sent)
    assert "?leak=" not in str(client.sent)
    assert "hunter2" not in (tmp_path / "run-d" / "events.jsonl").read_text()


def test_sensitive_literals_in_artifact_arguments_are_rejected(tmp_path):
    client = ScriptedClient([
        Turn(ToolUse("click", {"role": "button", "name": "hunter2",
                               "rationale": "hunter2"})),
        Turn(ToolUse("complete", {"kind": "visible_text", "text": "done"})),
    ])
    surface = FakeSurface(page_text="done")
    runner = _runner(client, surface, tmp_path)
    runner.set_runtime_values({"password": "hunter2"})

    assert runner.run() is None
    assert surface.actions == []
    assert "hunter2" not in str(client.sent)
    assert "hunter2" not in (tmp_path / "run-d" / "events.jsonl").read_text()


def test_offsite_redirect_stops_same_turn_before_later_actions(tmp_path):
    class RedirectSurface(FakeSurface):
        def navigate(self, url, timeout_ms):
            super().navigate(url, timeout_ms)
            self.set_state(url="https://ads.example.com/landing")

    client = ScriptedClient([Turn(
        ToolUse("navigate", {"url": "https://automationexercise.com/products"}),
        ToolUse("click", {"role": "button", "name": "Search", "rationale": "Search button."}),
    )])
    surface = RedirectSurface()

    assert _runner(client, surface, tmp_path).run() is None
    assert ("click", "Search") not in surface.actions


def test_malformed_completion_returns_no_artifact_without_crashing(tmp_path):
    client = ScriptedClient([Turn(ToolUse("complete", {"kind": "visible_text"}))])

    assert _runner(client, FakeSurface(), tmp_path).run() is None


def test_missing_runtime_input_is_not_replaced_with_a_literal(tmp_path):
    client = ScriptedClient([
        Turn(ToolUse("fill", {"role": "textbox", "name": "Search Product",
                              "value_from_input": "product", "rationale": "Search field."})),
        Turn(ToolUse("complete", {"kind": "visible_text", "text": "done"})),
    ])
    surface = FakeSurface(page_text="done")

    assert _runner(client, surface, tmp_path).run() is None
    assert surface.actions == []


def test_deadline_bounds_model_request_and_prevents_late_actions(tmp_path, monkeypatch):
    now = [0.0]

    class DelayedClient(ScriptedClient):
        def create(self, **kwargs):
            response = super().create(**kwargs)
            now[0] = 2.0
            return response

    monkeypatch.setattr(discovery.time, "monotonic", lambda: now[0])
    client = DelayedClient([Turn(ToolUse("click", {
        "role": "button", "name": "Search", "rationale": "Search button.",
    }))])
    surface = FakeSurface()
    runner = _runner(client, surface, tmp_path)
    runner._max_seconds = 1

    assert runner.run() is None
    assert client.sent[0]["timeout"] <= 1
    assert surface.actions == []


def test_external_client_errors_stop_discovery_without_exposing_the_error(tmp_path):
    class FailingClient:
        class Messages:
            def create(self, **kwargs):
                raise RuntimeError("hunter2 client failure")

        def __init__(self):
            self.messages = self.Messages()

    runner = _runner(FailingClient(), FakeSurface(), tmp_path)
    runner.set_runtime_values({"password": "hunter2"})

    assert runner.run() is None
    assert "hunter2" not in (tmp_path / "run-d" / "events.jsonl").read_text()


def test_events_record_redacted_tool_arguments_and_results(tmp_path):
    surface = FakeSurface(url="https://automationexercise.com/", page_text="Home")
    client = ScriptedClient([
        Turn(ToolUse("fill", {"kind": "role_name", "role": "textbox", "name": "Password",
                              "value_from_input": "password",
                              "rationale": "the labelled password field"})),
        Turn(ToolUse("complete", {"kind": "visible_text", "text": "Home"})),
    ])
    runner = _runner(client, surface, tmp_path)
    runner.set_runtime_values({"password": "s3cret-value", "product": "Blue Top"})
    runner.run()

    raw = (tmp_path / "run-d" / "events.jsonl").read_text()
    events = [json.loads(line) for line in raw.splitlines()]
    call = next(e for e in events if e["type"] == "tool_call" and e["tool"] == "fill")
    assert call["args"]["name"] == "Password"
    assert call["args"]["rationale"] == "the labelled password field"
    assert any(e["type"] == "tool_result" and e["tool"] == "fill" for e in events)
    assert "s3cret-value" not in raw


def test_events_record_the_models_own_words(tmp_path):
    class Text:
        type = "text"

        def __init__(self, text):
            self.text = text

    client = ScriptedClient([
        Turn(Text("I will open the products page first."),
             ToolUse("navigate", {"url": "https://automationexercise.com/products"})),
        Turn(ToolUse("complete", {"kind": "visible_text", "text": "done"})),
    ])
    _runner(client, FakeSurface(page_text="done"), tmp_path).run()
    events = [json.loads(line) for line in (tmp_path / "run-d" / "events.jsonl").read_text().splitlines()]
    said = next(e for e in events if e["type"] == "model_text")
    assert said["text"] == "I will open the products page first."


def test_an_unexpected_error_records_its_type_and_a_screenshot(tmp_path):
    class Exploding:
        messages = property(lambda self: self)

        def create(self, **kwargs):
            raise RuntimeError("connection reset")

    surface = FakeSurface()
    runner = _runner(Exploding(), surface, tmp_path)
    assert runner.run() is None
    events = [json.loads(line) for line in (tmp_path / "run-d" / "events.jsonl").read_text().splitlines()]
    stopped = next(e for e in events if e["type"] == "discovery_stopped")
    assert stopped["reason"] == "external_error"
    assert stopped["error_type"] == "RuntimeError"
    assert "connection reset" not in json.dumps(events)
    assert len(surface.screenshots) == 1
    assert stopped["screenshot"] == surface.screenshots[0]


def test_events_record_each_invalid_tool_result_once(tmp_path):
    client = ScriptedClient([
        Turn(
            ToolUse("not_a_tool", {}),
            ToolUse("complete", {"kind": "visible_text"}),
        ),
        Turn(ToolUse("escalate", {"reason": "Stopping after invalid calls."})),
    ])

    assert _runner(client, FakeSurface(), tmp_path).run() is None

    events = [json.loads(line) for line in (tmp_path / "run-d" / "events.jsonl").read_text().splitlines()]
    results = [event for event in events if event["type"] == "tool_result"]
    assert [(event["tool"], event["result"]) for event in results] == [
        ("", "Invalid tool arguments."),
        ("complete", "Invalid tool arguments."),
    ]


def test_stopped_screenshot_masks_a_sensitive_fill_that_raises(tmp_path):
    surface = FakeSurface(fail_once_on={"fill"})
    client = ScriptedClient([
        Turn(ToolUse("fill", {"role": "textbox", "name": "Password",
                              "value_from_input": "password", "rationale": "Password field."})),
    ])
    runner = _runner(client, surface, tmp_path)
    runner.set_runtime_values({"password": "s3cret-value"})

    assert runner.run() is None

    assert [[spec.primary.name for spec in masks] for masks in surface.screenshot_masks] == [["Password"]]
    assert "s3cret-value" not in (tmp_path / "run-d" / "events.jsonl").read_text()


def test_completion_that_crosses_deadline_returns_no_artifact(tmp_path, monkeypatch):
    now = [0.0]

    class LateCompletionSurface(FakeSurface):
        def page_contains(self, text):
            now[0] = 2.0
            return super().page_contains(text)

    monkeypatch.setattr(discovery.time, "monotonic", lambda: now[0])
    client = ScriptedClient([
        Turn(ToolUse("navigate", {"url": "https://automationexercise.com/products"})),
        Turn(ToolUse("complete", {"kind": "visible_text", "text": "done"})),
    ])
    runner = _runner(client, LateCompletionSurface(page_text="done"), tmp_path)
    runner._max_seconds = 1

    assert runner.run() is None


def test_navigation_artifact_keeps_replay_url_while_messages_strip_query_and_fragment(tmp_path):
    url = "https://automationexercise.com/products?category=shirts#featured"
    client = ScriptedClient([
        Turn(ToolUse("navigate", {"url": url})),
        Turn(ToolUse("complete", {"kind": "visible_text", "text": "done"})),
    ])
    artifact = _runner(client, FakeSurface(page_text="done"), tmp_path).run()

    assert artifact.steps[0].url == url
    assert "?category=shirts" not in str(client.sent)
    assert "#featured" not in str(client.sent)


@pytest.mark.parametrize("kind", ["element_visible", "element_absent", "value_equals"])
def test_element_condition_kind_is_not_used_as_locator_kind(kind):
    args = {"kind": kind, "role": "heading", "name": "Account Created!"}
    if kind == "value_equals":
        args["expected"] = "Account Created!"

    condition = discovery._condition_from(args)

    assert condition.kind == kind
    assert condition.target.primary.kind == "role_name"


def test_declared_outcomes_reach_the_artifact_without_adding_a_step(tmp_path):
    surface = FakeSurface(url="https://automationexercise.com/products",
                          page_text="Searched Products")
    client = ScriptedClient([
        Turn(ToolUse("navigate", {"url": "https://automationexercise.com/products"})),
        Turn(ToolUse("declare_outcome", {
            "code": "product_not_found",
            "kind": "visible_text",
            "text": "No products found",
            "outcome_description": "The searched product does not exist.",
        })),
        Turn(ToolUse("complete", {"kind": "visible_text", "text": "Searched Products"})),
    ])
    artifact = _runner(client, surface, tmp_path).run()
    assert [o.code for o in artifact.business_outcomes] == ["product_not_found"]
    assert artifact.business_outcomes[0].when.text == "No products found"
    assert artifact.business_outcomes[0].description == "The searched product does not exist."
    assert [s.action for s in artifact.steps] == ["navigate"]


def test_an_outcome_can_be_scoped_to_a_recorded_step(tmp_path):
    surface = FakeSurface(url="https://automationexercise.com/products",
                          page_text="Searched Products")
    client = ScriptedClient([
        Turn(ToolUse("navigate", {"url": "https://automationexercise.com/products"})),
        Turn(ToolUse("declare_outcome", {"code": "product_not_found", "step_id": "s01",
                                         "kind": "visible_text",
                                         "text": "No products found"})),
        Turn(ToolUse("complete", {"kind": "visible_text", "text": "Searched Products"})),
    ])
    artifact = _runner(client, surface, tmp_path).run()
    assert artifact.business_outcomes == []
    assert [o.code for o in artifact.steps[0].business_outcomes] == ["product_not_found"]


def test_an_outcome_naming_an_unknown_step_is_rejected(tmp_path):
    surface = FakeSurface(url="https://automationexercise.com/products",
                          page_text="Searched Products")
    client = ScriptedClient([
        Turn(ToolUse("navigate", {"url": "https://automationexercise.com/products"})),
        Turn(ToolUse("declare_outcome", {"code": "product_not_found", "step_id": "s99",
                                         "kind": "visible_text",
                                         "text": "No products found"})),
        Turn(ToolUse("complete", {"kind": "visible_text", "text": "Searched Products"})),
    ])
    artifact = _runner(client, surface, tmp_path).run()
    assert artifact.business_outcomes == []
    assert artifact.steps[0].business_outcomes == []
    assert client.sent[-1]["messages"][-1]["content"][0]["content"].startswith(
        "No recorded step has that id")


def test_an_outcome_without_a_code_is_rejected(tmp_path):
    surface = FakeSurface(url="https://automationexercise.com/products",
                          page_text="Searched Products")
    client = ScriptedClient([
        Turn(ToolUse("navigate", {"url": "https://automationexercise.com/products"})),
        Turn(ToolUse("declare_outcome", {"kind": "visible_text", "text": "x"})),
        Turn(ToolUse("complete", {"kind": "visible_text", "text": "Searched Products"})),
    ])
    artifact = _runner(client, surface, tmp_path).run()
    assert artifact.business_outcomes == []
    assert client.sent[-1]["messages"][-1]["content"][0]["content"] == "Invalid tool arguments."
