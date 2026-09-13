# Assignment Audit Remediation Implementation Plan

> Companion to `2026-09-09-computer-use-automation-implementation.md`. The design decisions
> this plan settles (Tasks 1, 2, 6, 7, 8, 9, 10) are appended to `decisions.md` in Task 11,
> continuing its numbered format.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the gaps an evaluator would find between the submission and Assignment A —
principally that no shipped artifact was emitted by discovery, that the multi-tenant demo
cannot run un-overridden, and that discovery evidence records verbs without arguments.

**Architecture:** No new modules and no new dependencies. Every change extends an existing
seam: three new fields/tools on the discovery side (`derived_from`, `declare_outcome`,
`checkpoint(step_id)`), one new behaviour on the replay side (tenant URL rebasing plus
interstitial recovery on blocked actions), and a second copy of the local legacy page so the
tenant profile has a genuinely different surface to point at. The public-site artifacts gain
checkpoints and fallbacks; nothing about the schema's shape changes.

**Tech Stack:** Python 3.12, Pydantic v2, Playwright (sync API), Anthropic SDK, pytest.
Standard library only for CLI, JSON Lines, and serving the legacy pages (`http.server`).

**Spec:** `docs/superpowers/specs/2026-09-08-computer-use-automation-design.md`, with
`decisions.md` as the reasoning log. The audit findings this plan answers are restated per
task so an executor does not need the audit transcript.

## Global Constraints

- Python 3.12. Runtime dependencies stay limited to `anthropic`, `playwright`, `pydantic`.
  Test dependency: `pytest` only. **Add no new dependency in any task.**
- **Never run `git commit`.** Every task ends by staging changes with `git add`; Aryan
  commits manually. This overrides the commit step in any skill.
- **Every code change is made by a dispatched subagent, not inline**, and the
  code-reviewer agent must review a task's code before that task is marked done.
- Every Pydantic model keeps `model_config = ConfigDict(extra="forbid")`.
  `CapabilityArtifact` additionally keeps `protected_namespaces=()`.
- `schema_version` stays exactly `"1.0"`. Adding optional fields with defaults is a
  backward-compatible change; every artifact already on disk must still validate.
- Substring matching on origins is forbidden anywhere in the codebase. Origin matching stays
  parsed scheme + exact host + exact port.
- Sensitive values never reach an artifact, a log, a screenshot, or the model.
- `pytest` must pass offline, with no API key and no browser, at every task boundary.
  Baseline is 147 passing tests in ~0.25s; that speed is a feature — do not add a test that
  needs Playwright.
- `timeout_ms` stays `> 0` and `<= 30000`.

---

## File Structure

| File | Change |
|---|---|
| `automation/models.py` | Add `CapabilityArtifact.derived_from`. Delete three unused fields. |
| `automation/discovery.py` | Add the `declare_outcome` tool; `checkpoint` gains `step_id`; events carry redacted arguments, results, and typed error names. |
| `automation/replay.py` | `_apply_tenant` rebases navigate URLs onto `TenantProfile.base_url`; `_act` attempts interstitial dismissal on a blocked click/fill/select. |
| `automation/policy.py` | Unchanged. |
| `automation/cli.py` | `_policy()` takes `allow_dev`; `--allow-dev-origins` added to `discover`, `replay`, `capabilities invoke`. |
| `automation/surface.py` | Remove the stray section marker; move the Playwright imports to the top. |
| `automation/handoff.py` | Remove the stray `# ponytail:` token from the comment. |
| `legacy/base/index.html` | New — the vendor-default variant, generic control names. |
| `legacy/variant_b/index.html` | New — the current NorthStar-branded variant, moved from `legacy/index.html`. |
| `evidence/artifacts/legacy_product_lookup.json` | v3: accessible-name locators, fallbacks, checkpoints, a `product_not_found` outcome, no explicit consent step. |
| `evidence/artifacts/{prepare_product_checkout,register_test_account,delete_test_account}.json` | Checkpoints on state-changing steps; one declared fallback; `derived_from` set. |
| `config/tenants/legacy_variant.json` | v2: `base_url` port 8001, overrides for the four renamed controls. |
| `config/policy.json` | Add the `127.0.0.1:8001` dev-only origin. |
| `tests/test_models.py`, `test_discovery.py`, `test_replay.py`, `test_cli.py` | New tests per task. |
| `README.md`, `REPORT.md`, `decisions.md` | Updated in Task 11 against the new evidence. |

---

### Task 1: Artifact provenance becomes a lineage

**Audit finding.** All four shipped artifacts carry `provenance: "hand_authored"`, which
reads as "written by hand" rather than "reviewed derivative of a real discovery run." The
brief's through-line is *the model discovers → the artifact becomes a capability*, so the
link from a derivative back to its discovery must be machine-readable.

**Files:**
- Modify: `automation/models.py:164-198` (`CapabilityArtifact`)
- Modify: `automation/catalog.py:37-41` (`list`)
- Test: `tests/test_models.py`, `tests/test_catalog.py`

**Interfaces:**
- Produces: `CapabilityArtifact.derived_from: str | None` — the `discovery_run_id` of the
  run a reviewed derivative was built from. Tasks 9 and 11 populate it.

- [ ] **Step 1: Write the failing tests**

In `tests/test_models.py` — this file does not currently import the shared fixture, so add
`from tests.fakes import checkout_artifact` to its imports:

```python
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
```

In `tests/test_catalog.py`:

```python
def test_listing_exposes_the_derivation_of_a_reviewed_artifact(tmp_path):
    artifact = checkout_artifact(provenance="hand_authored", derived_from="discovery-abc")
    (tmp_path / "c.json").write_text(artifact.model_dump_json())
    assert CapabilityCatalog(tmp_path).list()[0]["derived_from"] == "discovery-abc"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_models.py tests/test_catalog.py -v`
Expected: FAIL — `ValidationError: Extra inputs are not permitted [type=extra_forbidden]`
for `derived_from`, and `KeyError: 'derived_from'` in the catalog test.

- [ ] **Step 3: Add the field and its validator**

In `automation/models.py`, inside `CapabilityArtifact`, immediately after the `provenance`
field:

```python
    derived_from: str | None = None
```

Then extend the existing `_check_references` validator — add this before its `return self`:

```python
        if self.derived_from and self.provenance != "hand_authored":
            raise ValueError(
                "derived_from records the discovery run a reviewed derivative was "
                "built from; a discovered artifact is its own source"
            )
```

In `automation/catalog.py`, add the key to the dict built by `list`:

```python
    def list(self) -> list[dict]:
        return [{"name": a.name, "description": a.description,
                 "artifact_version": a.artifact_version,
                 "provenance": a.provenance,
                 "derived_from": a.derived_from}
                for a in sorted(self._load_all().values(), key=lambda a: a.name)]
```

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: PASS, count 147 + 4.

- [ ] **Step 5: Stage (do not commit)**

```bash
git add automation/models.py automation/catalog.py tests/test_models.py tests/test_catalog.py
```

---

### Task 2: Discovery can declare business outcomes

**Audit finding.** This is the root cause of Task 1's symptom. The discovery tool set has no
way to record a business outcome, so a discovered artifact can never satisfy §3.3's
"expected business outcome vs. recoverable vs. hard failure" taxonomy, and every artifact
has to be hand-finished before it is usable. A declared outcome describes a *branch that is
not currently taken*, so — unlike `checkpoint` — it must never be evaluated against the live
page, and it must not add a step.

**Files:**
- Modify: `automation/discovery.py:71-100` (`TOOLS`), `113-165` (`ArtifactRecorder`),
  `289-363` (`_execute`), `365-369` (`_call_parts`)
- Test: `tests/test_discovery.py`

**Interfaces:**
- Consumes: `_condition_from(args)` and `BusinessOutcomeSpec` (already imported paths).
- Produces: `ArtifactRecorder.declare_outcome(code: str, condition: ConditionSpec,
  description: str) -> None`; the artifact returned by `finish()` now carries
  `business_outcomes`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_discovery.py`:

```python
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
    assert [s.action for s in artifact.steps] == ["navigate"]


def test_an_outcome_is_recorded_even_though_it_is_false_on_the_current_page(tmp_path):
    surface = FakeSurface(url="https://automationexercise.com/products",
                          page_text="Searched Products")
    client = ScriptedClient([
        Turn(ToolUse("navigate", {"url": "https://automationexercise.com/products"})),
        Turn(ToolUse("declare_outcome", {"code": "product_not_found",
                                         "kind": "visible_text",
                                         "text": "No products found"})),
        Turn(ToolUse("complete", {"kind": "visible_text", "text": "Searched Products"})),
    ])
    artifact = _runner(client, surface, tmp_path).run()
    assert artifact.business_outcomes[0].code == "product_not_found"


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_discovery.py -k outcome -v`
Expected: FAIL — the runner returns `"Unknown tool."` and `business_outcomes` stays empty.

- [ ] **Step 3: Add the tool, the recorder method, and the branch**

In `automation/discovery.py`, import `BusinessOutcomeSpec` by adding it to the existing
`from automation.models import (...)` block.

Append to `TOOLS`, after the `checkpoint` entry:

```python
    _tool(
        "declare_outcome",
        "Record an expected business result the caller must know about — a "
        "'no such record' page, a permission denial, an expired session. This is "
        "not a failure and not a checkpoint: the condition describes a branch that "
        "is NOT true right now, so it is stored, never evaluated.",
        {**_CONDITION["properties"],
         "code": {"type": "string",
                  "description": "snake_case outcome code, e.g. product_not_found."},
         "outcome_description": {"type": "string",
                                 "description": "What the caller should understand."}},
        ["code", "kind"],
    ),
```

In `ArtifactRecorder.__init__`, after `self._outputs`:

```python
        self._outcomes: list[BusinessOutcomeSpec] = []
```

Add the method after `attach_checkpoint`:

```python
    def declare_outcome(self, code: str, condition: ConditionSpec,
                        description: str = "") -> None:
        """Store an expected business branch. Never evaluated at record time."""
        self._outcomes.append(
            BusinessOutcomeSpec(code=code, when=condition, description=description))
```

In `finish`, add to the `CapabilityArtifact(...)` call, after `success_condition=`:

```python
            business_outcomes=self._outcomes,
```

In `_execute`, widen the first membership guard to include the new tool:

```python
            if name not in {"observe", "navigate", "click", "fill", "select", "extract",
                            "checkpoint", "declare_outcome"}:
                return "Unknown tool."
```

Then insert this branch immediately after the `if name == "observe":` block and **before**
the `self._policy.check_action(...)` line — declaring an outcome touches no surface and
needs no action permission:

```python
            if name == "declare_outcome":
                code = args.get("code")
                if not isinstance(code, str) or not code.strip():
                    return "Invalid tool arguments."
                try:
                    condition = _condition_from(args)
                except (KeyError, TypeError, ValueError):
                    return "Invalid tool arguments."
                self._recorder.declare_outcome(
                    self._safe_text(code.strip()), condition,
                    self._safe_text(str(args.get("outcome_description") or "")),
                )
                return f"Recorded business outcome {code.strip()}."
```

In `_call_parts`, add `"declare_outcome"` to the accepted-name set.

Finally, extend `SYSTEM_PROMPT` with one rule, placed before the `complete` rule:

```
- When you see that a step could legitimately end differently — no such record,
  permission denied, session expired — call declare_outcome once for that branch.
  It is a result the caller needs, not a failure.
```

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: PASS, previous count + 3.

- [ ] **Step 5: Stage**

```bash
git add automation/discovery.py tests/test_discovery.py
```

---

### Task 3: Checkpoints can attach to a named step

**Audit finding.** `attach_checkpoint` only decorates the *last* recorded step, so the model
cannot go back and assert a state for an earlier action. Combined with Task 2 this is the
second reason a discovered artifact is always incomplete.

**Files:**
- Modify: `automation/discovery.py:97` (the `checkpoint` tool schema), `146-148`
  (`attach_checkpoint`), `315-324` (the `checkpoint` branch of `_execute`)
- Test: `tests/test_discovery.py`

**Interfaces:**
- Produces: `ArtifactRecorder.attach_checkpoint(condition: ConditionSpec,
  step_id: str | None = None) -> bool` — returns `False` when `step_id` names no recorded
  step. The no-argument call keeps its current "decorate the last step" behaviour.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_checkpoint_can_attach_to_an_earlier_step(tmp_path):
    surface = FakeSurface(url="https://automationexercise.com/", page_text="Home")
    client = ScriptedClient([
        Turn(ToolUse("navigate", {"url": "https://automationexercise.com/products"})),
        Turn(ToolUse("click", {"kind": "role_name", "role": "button", "name": "Search",
                               "rationale": "the accessible submit control"})),
        Turn(ToolUse("checkpoint", {"step_id": "s01", "kind": "url_matches",
                                    "pattern": r".*/products"})),
        Turn(ToolUse("complete", {"kind": "visible_text", "text": "Home"})),
    ])
    artifact = _runner(client, surface, tmp_path).run()
    assert artifact.steps[0].expect.pattern == r".*/products"
    assert artifact.steps[1].expect is None


def test_a_checkpoint_naming_an_unknown_step_is_rejected(tmp_path):
    surface = FakeSurface(url="https://automationexercise.com/", page_text="Home")
    client = ScriptedClient([
        Turn(ToolUse("navigate", {"url": "https://automationexercise.com/products"})),
        Turn(ToolUse("checkpoint", {"step_id": "s99", "kind": "url_matches",
                                    "pattern": r".*/products"})),
        Turn(ToolUse("complete", {"kind": "visible_text", "text": "Home"})),
    ])
    artifact = _runner(client, surface, tmp_path).run()
    assert artifact.steps[0].expect is None
```

Note on the first test: `FakeSurface.navigate` sets the URL, so `url_matches` is true when
the checkpoint is evaluated; the point under test is *where it lands*, not whether it holds.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_discovery.py -k checkpoint -v`
Expected: FAIL — the checkpoint lands on `steps[1]`, and the unknown-id case silently
decorates the last step.

- [ ] **Step 3: Implement**

Add `step_id` to the `checkpoint` tool's properties — it must be declared explicitly because
`_CONDITION["properties"]` is shared with `complete` and `declare_outcome`, which have no
steps to attach to:

```python
    _tool(
        "checkpoint",
        "Assert an expected page state and attach it to a recorded step. Omit "
        "step_id to attach to the step you just took.",
        {**_CONDITION["properties"],
         "step_id": {"type": "string",
                     "description": "Recorded step id, e.g. s03. Defaults to the latest."}},
        ["kind"],
    ),
```

Replace `attach_checkpoint`:

```python
    def attach_checkpoint(self, condition: ConditionSpec,
                          step_id: str | None = None) -> bool:
        """Attach a checkpoint to one recorded step. False when step_id is unknown."""
        if step_id is None:
            if not self._steps:
                return False
            index = len(self._steps) - 1
        else:
            index = next((i for i, s in enumerate(self._steps) if s.id == step_id), -1)
            if index < 0:
                return False
        self._steps[index] = self._steps[index].model_copy(update={"expect": condition})
        return True
```

In the `checkpoint` branch of `_execute`, replace the `attach_checkpoint` call and its
return:

```python
                step_id = args.get("step_id")
                if step_id is not None and not isinstance(step_id, str):
                    return "Invalid tool arguments."
                if not self._recorder.attach_checkpoint(condition, step_id):
                    return "No recorded step has that id. Call checkpoint without step_id."
                return "Checkpoint holds."
```

`_condition_from` ignores the extra `step_id` key, so it needs no change.

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: PASS, previous count + 2.

- [ ] **Step 5: Stage**

```bash
git add automation/discovery.py tests/test_discovery.py
```

---

### Task 4: Discovery evidence records arguments, results, and error types

**Audit finding.** `events.jsonl` for a discovery run holds only `{ts, type, tool, turn}` —
no arguments, no chosen locator, no tool result, no model text. §3.5 asks for "a structured
log of what the agent did **and why**"; the why is absent. This is not hypothetical:
`evidence/discovery-aa0cef.../` escalated because every `element_visible` condition returned
"Invalid tool arguments", and nothing in the log can explain it. Separately,
`except Exception: return None` in `run()` collapses any bug into `reason="external_error"`.

**Files:**
- Modify: `automation/discovery.py:220` (the `tool_call` event), `267` (the result append),
  `275-280` (the `run()` handlers), `360-363` (the `_execute` catch-all)
- Test: `tests/test_discovery.py`

- [ ] **Step 1: Write the failing tests**

```python
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


def test_an_unexpected_error_records_its_type(tmp_path):
    class Exploding:
        messages = property(lambda self: self)

        def create(self, **kwargs):
            raise RuntimeError("connection reset")

    runner = _runner(Exploding(), FakeSurface(), tmp_path)
    assert runner.run() is None
    events = [json.loads(l) for l in (tmp_path / "run-d" / "events.jsonl").read_text().splitlines()]
    stopped = next(e for e in events if e["type"] == "discovery_stopped")
    assert stopped["reason"] == "external_error"
    assert stopped["error_type"] == "RuntimeError"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_discovery.py -k "arguments or error_type" -v`
Expected: FAIL — `KeyError: 'args'` and `KeyError: 'error_type'`.

- [ ] **Step 3: Implement**

Replace the `tool_call` event in `run()`:

```python
                    self._evidence.event("tool_call", tool=self._safe_text(name or ""),
                                         turn=turn, args=self._safe_data(args or {}))
```

`_safe_data` already redacts strings and strips URL query/fragment; `EvidenceWriter.event`
then applies key-name and value redaction on top, so a secret cannot survive either path.

Replace the final dispatch line in `run()`:

```python
                    text = self._execute(name, args)
                    self._evidence.event("tool_result", tool=name, turn=turn,
                                         result=self._safe_text(text)[:500])
                    results.append(self._result(call, text))
```

Replace the two catch-alls. In `run()`:

```python
        except Exception as exc:
            self._evidence.event("discovery_stopped", reason="external_error",
                                 error_type=type(exc).__name__)
            return None
```

In `_execute`:

```python
        except Exception as exc:
            self._evidence.event("action_error", tool=name,
                                 error_type=type(exc).__name__)
            raise _DiscoveryStopped("action_error") from None
```

Deliberately keep recording the exception *type* and not its message: a Playwright error
message can quote page content, and page content is untrusted and may carry PII.

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: PASS, previous count + 2.

- [ ] **Step 5: Stage**

```bash
git add automation/discovery.py tests/test_discovery.py
```

---

### Task 5: Dev-only origins are denied unless explicitly enabled

**Audit finding.** `PolicyEngine.__init__` defaults `allow_dev_origins=True` and the CLI
never passes `False`, so the plaintext `http://127.0.0.1:8000` origin is permitted on every
run, including live public-site runs. REPORT §6 cites "dev_only policy configuration" as
bounding the plaintext-HTTP limit; today nothing binds it.

**Files:**
- Modify: `automation/policy.py:53` (flip the default), `automation/cli.py:38-70`
  (`build_parser`), `150-154` (`_policy`), `184` and `233` (the call sites)
- Test: `tests/test_cli.py`, `tests/test_policy.py`

**Interfaces:**
- Produces: `automation.cli._policy(path: str, allow_dev: bool) -> PolicyEngine` — the
  second argument is now required at every call site.

- [ ] **Step 1: Write the failing tests**

In `tests/test_policy.py`:

```python
def test_dev_origins_are_denied_by_default():
    engine = PolicyEngine(Policy(
        allowed_origins=[{"scheme": "http", "host": "127.0.0.1", "port": 8000,
                          "dev_only": True}],
        allowed_actions=["navigate"]))
    with pytest.raises(PolicyDenied):
        engine.check_url("http://127.0.0.1:8000/")
```

In `tests/test_cli.py`:

```python
def test_replay_denies_the_loopback_origin_without_the_flag(tmp_path, monkeypatch):
    args = build_parser().parse_args([
        "replay", "--artifact", "a.json", "--inputs", "i.json"])
    assert args.allow_dev_origins is False


def test_the_flag_turns_the_loopback_origin_back_on(tmp_path):
    policy_file = tmp_path / "policy.json"
    policy_file.write_text(json.dumps({
        "allowed_origins": [{"scheme": "http", "host": "127.0.0.1", "port": 8000,
                             "dev_only": True}],
        "allowed_actions": ["navigate"]}))
    assert cli._policy(str(policy_file), allow_dev=True).check_url("http://127.0.0.1:8000/") is None
    with pytest.raises(PolicyDenied):
        cli._policy(str(policy_file), allow_dev=False).check_url("http://127.0.0.1:8000/")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_policy.py tests/test_cli.py -k dev -v`
Expected: FAIL — no `allow_dev_origins` attribute; `_policy()` takes one argument.

- [ ] **Step 3: Implement**

In `automation/policy.py`, flip the default so the safe value needs no caller cooperation:

```python
    def __init__(self, policy: Policy, allow_dev_origins: bool = False):
```

In `automation/cli.py`, add the flag to all three parsers that build an engine — `discover`,
`replay`, and `invoke`:

```python
    for parser_needing_dev in (discover, replay, invoke):
        parser_needing_dev.add_argument(
            "--allow-dev-origins", action="store_true",
            help="Permit origins marked dev_only in the policy file (local surfaces).")
```

Place that loop just before `return parser`, after `invoke` is fully defined.

Change `_policy`:

```python
def _policy(path: str, allow_dev: bool) -> PolicyEngine:
    try:
        return PolicyEngine(load_policy(path), allow_dev_origins=allow_dev)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValidationError):
        raise CliError("policy", "invalid file or fields") from None
```

Update both call sites to `_policy(args.policy, getattr(args, "allow_dev_origins", False))`
— `getattr` because `_capabilities` synthesises `args` for the invoke path.

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: PASS, previous count + 3. Any existing test that built a `PolicyEngine` for a
loopback URL must now pass `allow_dev_origins=True` explicitly; fix those rather than
restoring the old default.

- [ ] **Step 5: Stage**

```bash
git add automation/policy.py automation/cli.py tests/test_policy.py tests/test_cli.py
```

---

### Task 6: A tenant profile re-points entry URLs

**Audit finding.** `TenantProfile.base_url` and `product_version` are declared but read by no
code; `_apply_tenant` swaps only locators and conditions, so a navigate step still goes to
the artifact's recorded origin. That makes cross-tenant reuse structurally impossible, which
REPORT §4 concedes. §3.7 asks for exactly this seam.

**Files:**
- Modify: `automation/replay.py:120-136` (`_apply_tenant`)
- Test: `tests/test_replay.py`

**Interfaces:**
- Produces: `ReplayRunner._rebase(url: str) -> str` — swaps scheme and netloc for the
  tenant's, preserving path, query, and fragment. Policy still validates the result, so a
  tenant cannot rebase onto a disallowed origin.

- [ ] **Step 1: Make `_runner` accept a policy, then write the failing tests**

`tests/test_replay.py:20` hardcodes `policy=_engine()`, so a test cannot supply its own.
Widen it first — this is a one-line change that every existing call keeps working through:

```python
def _runner(surface, tmp_path, artifact=None, policy=None, **kw):
    artifact = artifact or checkout_artifact()
    return ReplayRunner(
        artifact=artifact,
        policy=policy or _engine(),
        evidence=EvidenceWriter(tmp_path, "run-t", artifact.sensitive_input_names()),
        surface=surface,
        **kw,
    )
```

Add a second engine helper beside `_engine()`:

```python
def _engine_allowing_loopback():
    return PolicyEngine(Policy(
        allowed_origins=[{"scheme": "https", "host": "automationexercise.com"},
                         {"scheme": "http", "host": "127.0.0.1", "port": 8001}],
        denied_route_patterns=["/payment*"],
        allowed_actions=["navigate", "click", "fill", "select", "extract", "assert"],
    ))
```

Then the tests, using the module's existing `INPUTS` constant:

```python
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


def test_no_tenant_leaves_navigation_untouched(tmp_path):
    surface = _happy_surface()
    _runner(surface, tmp_path).run(INPUTS)
    assert ("navigate", "https://automationexercise.com/products") in surface.actions
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_replay.py -k "rebas or tenant_profile" -v`
Expected: FAIL — the navigate action still targets `https://automationexercise.com/products`.

- [ ] **Step 3: Implement**

Add to the imports at the top of `automation/replay.py`:

```python
from urllib.parse import urlsplit, urlunsplit
```

Add the method to `ReplayRunner`:

```python
    def _rebase(self, url: str | None) -> str | None:
        """Re-point a recorded entry URL at the tenant's own origin.

        Only scheme and netloc move. The path is the part of a URL that
        encodes the flow, and a tenant running the same vendor product keeps
        it; what differs is where the product is hosted. Policy still checks
        the result, so a profile cannot widen the allowlist.
        """
        if not self._tenant or not url:
            return url
        base, target = urlsplit(self._tenant.base_url), urlsplit(url)
        if not base.scheme or not base.netloc:
            return url
        return urlunsplit((base.scheme, base.netloc, target.path,
                           target.query, target.fragment))
```

In `_apply_tenant`, replace the loop body:

```python
        for step in steps:
            locator = self._tenant.locator_overrides.get(step.id)
            condition = self._tenant.condition_overrides.get(step.id)
            rebased = self._rebase(step.url) if step.action == "navigate" else step.url
            if locator or condition or rebased != step.url:
                step = step.model_copy(update={
                    "target": locator or step.target,
                    "expect": condition or step.expect,
                    "url": rebased,
                })
                self._evidence.event("tenant_override", step_id=step.id,
                                     tenant=self._tenant.tenant_id,
                                     locator=bool(locator), condition=bool(condition),
                                     rebased_url=rebased if rebased != step.url else None)
            out.append(step)
```

Careful: compute `rebased != step.url` **before** `model_copy`, as written above — the
comparison after the copy would always be false.

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: PASS, previous count + 3.

- [ ] **Step 5: Stage**

```bash
git add automation/replay.py tests/test_replay.py
```

---

### Task 7: A blocked action attempts interstitial dismissal

**Audit finding.** `recoveries` is `[]` in all ten checked-in runs, so the brief's middle
error category — recoverable conditions — has unit tests but no run-level evidence.
`_dismiss_interstitial` exists but fires only on `LocatorNotFound`. A consent overlay is the
canonical case, and an overlay does not hide the control underneath it: the locator resolves
fine and the *click* times out on actionability. So the real-world trigger never reaches the
recovery path.

**Files:**
- Modify: `automation/replay.py:172-192` (`_act`)
- Test: `tests/test_replay.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_an_overlay_blocked_click_is_recovered_by_dismissing_it(tmp_path):
    surface = FakeSurface(
        url="https://automationexercise.com/",
        page_text="Review Your Order",
        visible=["Accept"],
        text_values={"Product Name": "Blue Top", "Total": "Rs. 500"},
        fail_once_on=["click"],
    )
    result = _runner(surface, tmp_path).run(INPUTS)
    assert result.status == "success"
    assert [r.kind for r in result.recoveries] == ["interstitial_dismissed"]
    assert ("click", "Accept") in surface.actions


def test_a_blocked_click_with_no_interstitial_is_a_hard_failure(tmp_path):
    surface = FakeSurface(url="https://automationexercise.com/",
                          fail_once_on=["click"])
    result = _runner(surface, tmp_path).run(INPUTS)
    assert result.status == "failure"
    assert result.failure.error_code == "timeout"
    assert result.recoveries == []
```

Note on the first test: `fail_once_on=["click"]` trips on the fixture's `submit_search`
step, `visible=["Accept"]` makes the interstitial resolvable, and `_dismiss_interstitial`
itself calls `click` — which by then has consumed its one failure, so the dismissal
succeeds and the retry goes through.

`FakeSurface._trip` already raises `TimeoutError` once for a named action, and `is_visible`
already answers from the `visible` set, so both tests need no fake changes.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_replay.py -k overlay -v`
Expected: FAIL — the first test returns `status == "failure"` with `error_code == "timeout"`.

- [ ] **Step 3: Implement**

Replace the `TimeoutError` handler in `_act`:

```python
        except TimeoutError as exc:
            if attempt == 1 and step.action == "navigate":
                self._recoveries.append(RecoveryRecord(step_id=step.id, kind="retried",
                                                       detail=str(exc)))
                self._evidence.event("recovered", step_id=step.id, kind="retried")
                return self._act(step, values, outputs, attempt + 1)
            # An overlay does not hide the control beneath it — the locator
            # resolves and the interaction is what gets intercepted. So a
            # blocked interaction, not just a missing element, is a reason to
            # look for a known interstitial. Bounded to one attempt either way.
            if (attempt == 1 and step.action in ("click", "fill", "select")
                    and self._dismiss_interstitial(step)):
                return self._act(step, values, outputs, attempt + 1)
            raise _Failure("timeout", f"step {step.id} to complete", str(exc))
```

The `attempt == 1` guard keeps recovery bounded to a single retry per step, which is what
makes this a *recoverable condition* rather than an unbounded retry loop.

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: PASS, previous count + 2.

- [ ] **Step 5: Stage**

```bash
git add automation/replay.py tests/test_replay.py
```

---

### Task 8: Two legacy variants, and a base artifact that runs un-overridden

**Audit finding.** This is the weakest requirement in the submission.
`legacy_product_lookup`'s base locators are placeholders — `button` matches any button,
`input#q` is a raw id — whose own rationales say "the tenant profile replaces this". The base
artifact therefore *cannot* run without overrides, which inverts the demonstration §3.7 asks
for: one reviewed flow, small per-tenant diff. There is also only one legacy page, so the
"variant" is a relabelling of the same file.

**Approach.** Split the page into two variants of the same vendor product, differing exactly
the way two tenants of one vendor differ: same structure and flow, different control names
and branding, different host. `legacy/base/index.html` keeps generic vendor-default names;
`legacy/variant_b/index.html` keeps the existing NorthStar branding. The artifact is recorded
against base and runs there unmodified; the tenant profile carries a `base_url` on a second
port (Task 6) plus four locator overrides. The consent overlay stays in both and is *not* a
step — Task 7's recovery handles it, which is what puts a real `RecoveryRecord` in evidence.

**Files:**
- Create: `legacy/base/index.html`, `legacy/variant_b/index.html`
- Delete: `legacy/index.html` (its content becomes `variant_b`)
- Modify: `evidence/artifacts/legacy_product_lookup.json` (→ v3),
  `config/tenants/legacy_variant.json` (→ port 8001),
  `config/policy.json` (add the 8001 dev-only origin)
- Test: `tests/test_replay.py` (artifact-shape assertions only — no browser)

- [ ] **Step 1: Create the two variants**

`legacy/variant_b/index.html` is the current `legacy/index.html` moved verbatim — nested
tables, no test IDs, the `Accept` overlay, `Item Lookup` / `Find Item` / `Item Description` /
`Amount Due`, and the fixed two-item catalog.

`legacy/base/index.html` is the same file with the vendor-default names and title. Change
exactly these five strings and nothing structural:

| variant_b | base |
|---|---|
| `<title>NorthStar Servicing Console</title>` | `<title>Servicing Console</title>` |
| `<label for="q">Item Lookup</label>` | `<label for="q">Product Search</label>` |
| `<button onclick="lookup()">Find Item</button>` | `<button onclick="lookup()">Search</button>` |
| `aria-label="Item Description"` | `aria-label="Product Name"` |
| `aria-label="Amount Due"` | `aria-label="Total"` |

Keep `<span role="heading" aria-level="2" ...>` in both — the accessible heading role is what
makes the surface reachable without a clean DOM, and it is the point the REPORT argues.
Keep the `No products found` branch in both; it becomes the declared business outcome.

- [ ] **Step 2: Rewrite the artifact to v3**

`evidence/artifacts/legacy_product_lookup.json`: `artifact_version: 3`, six steps become
five (the `dismiss_consent` step is removed), every locator becomes an accessible name with a
structural fallback, every step gains a checkpoint, and the not-found branch becomes a
declared outcome. The steps:

```json
[
  {"id": "start", "action": "navigate", "url": "http://127.0.0.1:8000/",
   "expect": {"kind": "element_visible",
              "target": {"primary": {"kind": "label", "value": "Product Search"}}}},

  {"id": "search", "action": "fill", "value_from_input": "product",
   "target": {"primary": {"kind": "label", "value": "Product Search"},
              "fallback": {"kind": "css", "value": "input#q"}},
   "locator_rationale": "The field is labelled, so the label is the portable primary; the id is a structural fallback for a variant that drops the label association.",
   "expect": {"kind": "element_visible",
              "target": {"primary": {"kind": "label", "value": "Product Search"}}}},

  {"id": "submit_search", "action": "click",
   "target": {"primary": {"kind": "role_name", "role": "button", "name": "Search"}},
   "business_outcomes": [
     {"code": "product_not_found",
      "when": {"kind": "visible_text", "text": "No products found"},
      "description": "The catalog has no item under that name."}]},

  {"id": "read_name", "action": "extract", "output_name": "product_name",
   "target": {"primary": {"kind": "role_name", "role": "heading", "name": "Product Name"}},
   "locator_rationale": "The result heading exposes an accessible name even though the markup is a span in a nested table."},

  {"id": "read_total", "action": "extract", "output_name": "amount_due",
   "target": {"primary": {"kind": "label", "value": "Total"}},
   "locator_rationale": "aria-label supplies the accessible name; the surrounding table cells carry no semantics."}
]
```

Set `success_condition` to `{"kind": "element_visible", "target": {"primary":
{"kind": "role_name", "role": "heading", "name": "Product Name"}}}` — the previous
`visible_text: "Blue Top"` hard-coded an input value into the success condition, which is a
schema smell in its own right. Keep `provenance: "hand_authored"`, `model_id: "none"`, and
set `derived_from: null` (this one has no discovery source, and Task 1's validator permits
that).

- [ ] **Step 3: Rewrite the tenant profile and widen the dev policy**

`config/tenants/legacy_variant.json`:

```json
{
  "tenant_id": "northstar_variant_b",
  "base_url": "http://127.0.0.1:8001",
  "product_version": "NorthStar Servicing Console 4.2",
  "locator_overrides": {
    "search": {"primary": {"kind": "label", "value": "Item Lookup"},
               "fallback": {"kind": "css", "value": "input#q"}},
    "submit_search": {"primary": {"kind": "role_name", "role": "button",
                                  "name": "Find Item"}},
    "read_name": {"primary": {"kind": "role_name", "role": "heading",
                              "name": "Item Description"}},
    "read_total": {"primary": {"kind": "label", "value": "Amount Due"}}
  },
  "condition_overrides": {
    "start": {"kind": "element_visible",
              "target": {"primary": {"kind": "label", "value": "Item Lookup"}}},
    "search": {"kind": "element_visible",
               "target": {"primary": {"kind": "label", "value": "Item Lookup"}}}
  }
}
```

In `config/policy.json`, add to `allowed_origins`:

```json
    {"scheme": "http", "host": "127.0.0.1", "port": 8001, "dev_only": true}
```

- [ ] **Step 4: Write the artifact-shape test**

In `tests/test_replay.py` — add `import json`, `from pathlib import Path`, and
`CapabilityArtifact` to its `automation.models` import. This runs offline and guards the
property that actually broke:

```python
def test_the_legacy_base_artifact_needs_no_tenant_overrides():
    artifact = CapabilityArtifact(
        **json.loads(Path("evidence/artifacts/legacy_product_lookup.json").read_text()))
    tenant = TenantProfile(
        **json.loads(Path("config/tenants/legacy_variant.json").read_text()))
    for step in artifact.steps:
        if step.target:
            assert step.target.primary.kind != "css", (
                f"{step.id}: the base artifact must resolve on the base variant "
                "without an override")
    assert set(tenant.locator_overrides) <= {s.id for s in artifact.steps}
```

- [ ] **Step 5: Verify end to end against both variants**

```bash
python -m http.server 8000 --bind 127.0.0.1 --directory legacy/base &
python -m http.server 8001 --bind 127.0.0.1 --directory legacy/variant_b &

# base: no tenant profile at all
python -m automation.cli replay --allow-dev-origins \
  --artifact evidence/artifacts/legacy_product_lookup.json \
  --inputs config/legacy_product_lookup.inputs.json

# variant B: same artifact, tenant profile only
python -m automation.cli replay --allow-dev-origins \
  --artifact evidence/artifacts/legacy_product_lookup.json \
  --inputs config/legacy_product_lookup.inputs.json \
  --tenant config/tenants/legacy_variant.json

# the declared business outcome, on both
python -m automation.cli replay --allow-dev-origins \
  --artifact evidence/artifacts/legacy_product_lookup.json \
  --inputs <(echo '{"product": "No Such Item"}')

kill %1 %2
```

Expected: runs 1 and 2 both `status: "success"` with `product_name` / `amount_due`, run 2's
events containing `tenant_override` lines with `rebased_url`; run 3
`status: "business_outcome"`, `outcome_code: "product_not_found"`. Each run's `recoveries`
should contain one `interstitial_dismissed` from the consent overlay. If it does not, the
overlay is not blocking the first interaction — check Task 7 before changing the artifact.

- [ ] **Step 6: Stage**

```bash
git add legacy config/tenants/legacy_variant.json config/policy.json \
        evidence/artifacts/legacy_product_lookup.json tests/test_replay.py \
        evidence/replay-legacy_product_lookup-*
```

---

### Task 9: Checkpoints and fallbacks on the three public artifacts

**Audit finding.** One `expect` across 19 checkout steps; 17 consecutive steps proceed
without verifying the click worked, which is why an early break surfaces as a late
`locator_not_found`. The glossary calls this out by name. Separately, `LocatorSpec.fallback`
is implemented and unit-tested but used by zero shipped locators.

**Files:**
- Modify: `evidence/artifacts/prepare_product_checkout.json` (→ v5),
  `evidence/artifacts/register_test_account.json` (→ v4),
  `evidence/artifacts/delete_test_account.json` (→ v5)
- Test: `tests/test_models.py`

**Rule:** every step that changes page state — `navigate`, and any `click` that submits or
transitions — carries an `expect`. `fill`/`select` steps do not need one; their effect is
verified by the checkpoint on the submit that follows.

- [ ] **Step 1: Add the checkpoints**

`prepare_product_checkout` — add `expect` to these steps (s20 already has one):

| step | action | `expect` |
|---|---|---|
| s02 | navigate /products | `{"kind": "url_matches", "pattern": ".*/products$"}` |
| s04 | click submit_search | `{"kind": "visible_text", "text": "Searched Products"}` |
| s05 | click View Product | `{"kind": "url_matches", "pattern": ".*/product_details/.*"}` |
| s07 | click Add to cart | `{"kind": "visible_text", "text": "Added!"}` |
| s08 | click View Cart | `{"kind": "url_matches", "pattern": ".*/view_cart"}` |
| s14 | click Proceed To Checkout | `{"kind": "visible_text", "text": "Register / Login"}` |
| s18 | click login | `{"kind": "visible_text", "text": "Logged in as"}` |

`register_test_account` — add to s04 (`click Signup`):
`{"kind": "visible_text", "text": "Enter Account Information"}`. s18 already has one.

`delete_test_account` — add to s01 (`navigate`):
`{"kind": "url_matches", "pattern": "automationexercise\\.com/?$"}`. s04 and s05 already have
checkpoints.

- [ ] **Step 2: Add one honest fallback per artifact**

Only add a fallback that can resolve *uniquely* — `_resolve` treats "matched several" as
"matched none", so an ambiguous fallback is worse than no fallback.

- `prepare_product_checkout` s03: primary `{"kind": "role_name", "role": "textbox",
  "name": "Search Product"}`, fallback `{"kind": "css", "value": "#search_product"}`,
  rationale: *"The search box exposes an accessible name; the id is the structural fallback
  for a variant that renders the placeholder differently."*
- `register_test_account` s06: primary `{"kind": "label", "value": "Password *"}`,
  fallback `{"kind": "css", "value": "input[data-qa=\"signup-password\"]"}`.
- `delete_test_account` s04: primary `{"kind": "role_name", "role": "button",
  "name": "Login"}`, fallback `{"kind": "css", "value": "button[data-qa=\"login-button\"]"}`.

Note the direction: the accessible name is the primary and the test ID is the *fallback*.
The current artifacts have this backwards in several places, which is what makes REPORT's
portability argument read as contradicted by its own artifacts.

- [ ] **Step 3: Set `derived_from` and bump versions**

On each of the three, set `provenance: "hand_authored"` (unchanged) and add:

| artifact | `derived_from` | new `artifact_version` |
|---|---|---|
| `prepare_product_checkout` | `discovery-e4e5dc356f484e87b62933aa0b84ba1a` | 5 |
| `register_test_account` | `discovery-13cca73621aa405b818c44398e093bfb` | 4 |
| `delete_test_account` | `discovery-09beb9662dce4374841ceb672a352cd2` | 5 |

- [ ] **Step 4: Write the guard test**

In `tests/test_models.py` — add `import json` and `from pathlib import Path`:

```python
SHIPPED = sorted(Path("evidence/artifacts").glob("*.json"))


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: p.stem)
def test_every_shipped_artifact_validates_and_checkpoints_its_transitions(path):
    artifact = CapabilityArtifact(**json.loads(path.read_text()))
    unchecked = [s.id for s in artifact.steps
                 if s.action in ("navigate", "click") and s.expect is None
                 and not s.business_outcomes and s.risk == "safe"]
    assert unchecked == [], f"{path.stem}: state-changing steps without a checkpoint"


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: p.stem)
def test_every_shipped_artifact_declares_at_least_one_fallback(path):
    artifact = CapabilityArtifact(**json.loads(path.read_text()))
    assert any(s.target and s.target.fallback for s in artifact.steps)
```

The first test exempts steps that carry a business outcome (the outcome *is* the
verification) and `requires_human` steps (a person verified the state).

- [ ] **Step 5: Run the suite**

Run: `pytest -q`
Expected: PASS. If the parametrised test fails for an artifact, add the missing checkpoint —
do not weaken the assertion.

- [ ] **Step 6: Stage**

```bash
git add evidence/artifacts tests/test_models.py
```

---

### Task 10: Remove dead fields and generation leftovers

**Audit finding.** `TargetSpec.supported_versions` is read by no code;
`TenantProfile.product_version` is read by no code (Task 6 wires `base_url`, not this);
`automation/surface.py:48` carries `# --- appended to automation/surface.py ---` and
`automation/handoff.py:141` begins `# ponytail:` — both read as generation leftovers;
`TargetSpec.vendor_product` is hardcoded to `"automationexercise"` in `discovery.py:160`
regardless of target; checked-in evidence embeds absolute `/Users/aryanmamidwar/...` paths.

**Decision to make first:** `product_version` is worth *keeping and documenting* rather than
deleting — it is the hook a drift check would read, and REPORT §4 owes §3.7 a drift answer.
`supported_versions` on `TargetSpec` is the same idea on the artifact side. Keep both, and
make them earn their place by having the runner warn when they disagree.

**Files:**
- Modify: `automation/replay.py` (version mismatch event), `automation/surface.py:48-51`,
  `automation/handoff.py:141`, `automation/discovery.py:160,176`,
  `automation/evidence.py:42-43` (relative screenshot paths)
- Test: `tests/test_replay.py`, `tests/test_evidence.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_replay.py` (add `import json` to its imports):

```python
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
```

In `tests/test_evidence.py` (add `from pathlib import Path`):

```python
def test_screenshot_paths_in_evidence_are_relative_to_the_repository(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    writer = EvidenceWriter(tmp_path, "run-x", set())
    assert not Path(writer.screenshot_path("failure")).is_absolute()
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_replay.py tests/test_evidence.py -k "drift or relative" -v`
Expected: FAIL — no `tenant_version_drift` event; `screenshot_path` returns an absolute path
when `root` is absolute.

- [ ] **Step 3: Implement**

In `ReplayRunner.run`, immediately after the `run_started` event:

```python
        supported = self._artifact.target.supported_versions
        running = self._tenant.product_version if self._tenant else None
        if supported and running and supported != running:
            # Drift is reported, never fatal: the artifact may well still work,
            # and a caller that blocks on a version string stops shipping.
            self._evidence.event("tenant_version_drift",
                                 artifact_supports=supported, tenant_runs=running)
```

In `EvidenceWriter.screenshot_path`, return a repo-relative path:

```python
    def screenshot_path(self, label: str) -> str:
        path = self.run_dir / f"{next(self._counter):03d}-{label}.png"
        try:
            return str(path.relative_to(Path.cwd()))
        except ValueError:
            return str(path)
```

In `automation/surface.py`, delete the line
`# --- appended to automation/surface.py ---` and move the three `playwright.sync_api`
imports up into the module's import block at the top.

In `automation/handoff.py:141`, drop the stray token so the comment reads
`# A timed-out terminal read cannot be cancelled portably; daemonizing keeps ...`.

In `automation/discovery.py`, stop hardcoding the vendor: add a
`vendor_product: str = "automationexercise"` parameter to `DiscoveryRunner.__init__` and to
`ArtifactRecorder.__init__`, thread it into the `TargetSpec(...)` call in `finish`, and pass
it from `cli._discover` derived from a new `--vendor-product` argument defaulting to
`"automationexercise"`.

- [ ] **Step 4: Run the suite**

Run: `pytest -q`
Expected: PASS, previous count + 2.

- [ ] **Step 5: Stage**

```bash
git add automation tests
```

---

### Task 11: Live evidence refresh and write-up alignment

**Audit finding.** Two claims in the submission outrun their evidence: no artifact was
emitted by discovery (`provenance: "discovered"` appears nowhere on disk), and the flagship
`prepare_product_checkout` has never replayed successfully — three business-outcome/failure
runs, zero successes, while the historical "successes" used a superseded contract with
exploratory outputs. Tasks 1–10 make both fixable; this task produces the evidence and makes
the prose match it.

**Files:**
- Create: new `evidence/discovery-*` and `evidence/replay-*` directories
- Modify: `README.md`, `REPORT.md`, `decisions.md`

- [ ] **Step 1: Produce a genuinely discovered artifact**

With `ANTHROPIC_API_KEY`, `AE_EMAIL`, `AE_PASSWORD` loaded per the README:

```bash
python -m automation.cli discover \
  --goal "Search for Blue Top on the products page and read its name and price. If the search returns no products, declare that as a business outcome." \
  --capability "lookup_product_$(date +%Y%m%d%H%M%S)" \
  --description "Read a product's name and price from the products listing." \
  --inputs config/inputs.example.json
```

Accept it only if the saved artifact has `provenance: "discovered"`, a non-empty
`business_outcomes`, and at least one `expect` — that is the whole point of Tasks 2 and 3. If
the model does not call `declare_outcome`, tighten the tool description rather than
hand-editing the artifact. Then replay it unchanged and keep both evidence directories.

- [ ] **Step 2: Land a successful checkout replay**

```bash
python -m automation.cli replay \
  --artifact evidence/artifacts/prepare_product_checkout.json \
  --inputs config/inputs.example.json
```

Expected: `status: "success"` with `product_name`, `unit_price`, `cart_total`. If a
checkpoint from Task 9 fails, the checkpoint is wrong about the site — fix the checkpoint,
not by deleting it. If the capability genuinely cannot pass, demote it in REPORT §3 and make
`register_test_account` the headline slice explicitly; do not leave the flagship unproven
and unmentioned.

- [ ] **Step 3: Rewrite the claims that changed**

`REPORT.md`:
- §2 — provenance is now a lineage: name the newly discovered artifact, and state that the
  three public artifacts are reviewed derivatives that point at their source run via
  `derived_from`. Delete the sentence conceding the current checkout contract has no
  successful replay, once Step 2 lands.
- §3 — cite the new checkout success; keep the retained failed run as historical evidence.
- §4 — this section changes most. Replace "This is not a claim of same-artifact cross-variant
  reuse" with what is now true: one artifact, two variants, `base_url` rebasing plus four
  locator overrides, and cite both runs. Add the drift answer §3.7 asks for and the current
  code now supports: `supported_versions` vs. `product_version` compared per run, emitted as
  `tenant_version_drift`, reported and never fatal — and say what the production version
  would add (a per-tenant replay canary and a stability signal), since that is a cut, not a
  claim.
- §6 — `dev_only` origins are now denied unless `--allow-dev-origins` is passed. The
  "loopback origin is the one plaintext-HTTP entry" limit becomes an opt-in, not a default.
- §7 — update the cuts list; remove the items this plan delivered.

`README.md`:
- Add `--allow-dev-origins` to the offline legacy command and serve two directories on ports
  8000 and 8001, showing both the un-overridden base run and the tenant run.
- Refresh the "Evidence" bullet list to the new run directories.

`decisions.md`: append numbered decisions continuing from 22, each with the alternatives and
why, for: `derived_from` lineage over a flat provenance enum (Task 1); `declare_outcome` as a
record-only tool that is never evaluated (Task 2); tenant rebasing limited to scheme+netloc
with the path treated as flow (Task 6); interstitial recovery on blocked interactions, not
just missing elements (Task 7); two legacy variants over one relabelled page (Task 8);
accessible name as primary with the test ID as fallback, not the reverse (Task 9); version
drift reported and never fatal (Task 10). Add a Change History line dated 2026-09-11.

- [ ] **Step 4: Final verification**

Run the full verification block below. Every claim left in REPORT must have a run behind it.

- [ ] **Step 5: Stage**

```bash
git add README.md REPORT.md decisions.md evidence
```

---

## Deliberately not in this plan

Named so an executor knows they were considered, not forgotten. Each belongs in REPORT §7
as a stated cut rather than in a task:

- **Widening the risky-action model.** `_deletes_account` matches only `delete|deletion` in
  a locator name or URL path, so "Remove", "Close account", "Transfer", "Approve" all pass as
  `safe`. A configurable risky-verb list in `config/policy.json` is the obvious fix, but the
  honest position is that keyword matching is the wrong mechanism at any vocabulary size —
  risk belongs on the artifact step, reviewed by a human, with policy as a backstop. Say that
  in §6 instead of growing the word list.
- **Boolean outputs that can be `false`.** `_coerce` returns `bool(raw.strip())`, so a
  boolean output is true whenever the extract succeeds and a hard failure otherwise;
  `account_created: false` is unrepresentable. This is defensible — a negative business fact
  is a business outcome, not a `false` — but it is currently undocumented. Document the
  convention in REPORT §2; do not change the coercion.
- **Committing and pushing.** Deliverable 1 is a public GitHub repo and nothing is committed
  yet. Aryan commits manually; this plan only stages. Decide separately whether
  `docs/superpowers/` belongs in a public submission.

## Verification

Run all of these before calling the work done. Aryan commits; do not.

1. `pytest -q` — green, and still under a second. Expect roughly 147 + 21 tests.
2. `python -m automation.cli capabilities list` — works with no API key; every entry shows
   `derived_from`, and at least one shows `provenance: "discovered"`.
3. Legacy base, **no** `--tenant`: `status: "success"` with both outputs, and one
   `interstitial_dismissed` recovery. This is the assertion that failed before Task 8.
4. Legacy variant B, same artifact plus `--tenant`: `status: "success"`, events show
   `tenant_override` with `rebased_url`.
5. Legacy, unknown product: `status: "business_outcome"`, `outcome_code:
   "product_not_found"`.
6. Loopback replay **without** `--allow-dev-origins`: `status: "failure"`,
   `error_code: "policy_origin_denied"`.
7. One live `discover` run whose saved artifact has `provenance: "discovered"`, non-empty
   `business_outcomes`, and at least one `expect`; then a replay of that artifact unchanged.
8. `prepare_product_checkout` replay: `status: "success"` with all three declared outputs.
9. `grep -rn "ponytail\|appended to automation" automation/` — no matches.
10. `grep -rln "/Users/aryanmamidwar" evidence/` — no matches in newly written runs.
11. Re-read REPORT §§2, 3, 4, 6 line by line against the evidence directories. Any sentence
    without a run behind it is either cut or moved to §7.
