# Assignment Audit Remediation Implementation Plan (v2)

> Companion to `2026-09-09-computer-use-automation-implementation.md`. Supersedes the v1
> remediation plan of the same date. The design decisions this plan settles (Tasks 1, 2, 3,
> 6, 7, 8, 9, 10) are appended to `decisions.md` in Task 11, continuing its numbered format.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the gaps an evaluator would find between the submission and Assignment A —
principally that no shipped artifact was emitted by discovery, that the multi-tenant demo
cannot run un-overridden, that discovery evidence records verbs without arguments, and that
the "recoverable condition" branch of the error taxonomy has no run-level evidence.

**Architecture:** No new modules and no new dependencies. Every change extends an existing
seam: three additions on the discovery side (`derived_from`, `declare_outcome`, an automatic
`url_matches` checkpoint on every recorded `navigate`), two on the replay side (tenant URL
rebasing; interstitial recovery when the surface reports an *intercepted* interaction via a
new `ActionBlocked` exception), and a second copy of the local legacy page so the tenant
profile has a genuinely different surface to point at. The public-site artifacts gain
checkpoints and fallbacks. `schema_version` stays `"1.0"`; every artifact already on disk
must still validate.

**Tech Stack:** Python 3.12, Pydantic v2, Playwright (sync API), Anthropic SDK, pytest.
Standard library only for CLI, JSON Lines, and serving the legacy pages (`http.server`).

**Spec:** `docs/superpowers/specs/2026-09-08-computer-use-automation-design.md`, with
`decisions.md` as the reasoning log. The audit findings this plan answers are restated per
task so an executor does not need the audit transcript.

## What changed from v1, and why

| v1 | v2 | Reason |
|---|---|---|
| Task 3 let `checkpoint` retro-attach to an earlier step via `step_id`. | Dropped. Replaced by an automatic `url_matches` checkpoint on every recorded `navigate` plus a prompt rule to checkpoint after each transition. | The v1 design evaluated the condition against the *current* page, so a checkpoint for an earlier step is either false (state has moved on) or, if skipped, an assertion that was never observed true. Neither is a checkpoint. |
| Task 7 retried a `click` after any `TimeoutError` if an interstitial was visible. | `PlaywrightSurface` raises `ActionBlocked` (a `TimeoutError` subclass) only when Playwright reports the element *intercepts pointer events*; replay recovers on that and nothing else. | `test_click_timeout_is_not_retried` encodes a deliberate safety rule: a timed-out click may have fired, and re-clicking can double-submit. An interception report is the one case where Playwright guarantees the click never happened. |
| Task 9's checkpoint table covered 10 steps; the guard test flagged every `navigate`/`click`. | Table covers every step the guard test flags (checkout s01/s13/s19, register s01/s05, delete s01 with the right URL). | The v1 table and its own test disagreed; the executor would have had to weaken one. |
| Task 9 swapped proven primaries for accessible-name primaries. | Keeps proven primaries, adds fallbacks only. | Changing a locator that has replayed successfully, without a live run, is drift introduced by the fix. |
| — | New Task 0: tests stop writing into `evidence/`; 174 empty run directories removed. | `tests/test_cli.py` calls `main()` without redirecting `EVIDENCE_ROOT`; each `pytest` run litters the evidence tree an evaluator will open. |
| Task 8 verified with `<(echo ...)`; tests used cwd-relative paths. | Checked-in `config/legacy_product_lookup.notfound.inputs.json`; tests anchor on `Path(__file__)`. | Reproducible from any cwd, on any shell. |
| Task 10 kept version fields "for a drift check" with no run showing drift. | Variant B declares version `4.3` against the artifact's `4.2`, so the tenant run emits a real `tenant_version_drift` event. | §3.7 asks how drift is *detected*; an event that never fires is not detection. |
| Task 11 replayed the discovered artifact and kept the evidence directories. | Also keeps the raw discovered JSON on disk, unedited, next to the reviewed derivatives. | `derived_from` is only credible if the source it names can be diffed against. |
| — | Priority order and a minimum viable cut. | The brief rewards a thin complete slice over polish; the executor needs to know what to drop under time pressure. |

## Priority order

Do the tasks in this order if time is short. Tasks 0–4 and 11 are the minimum viable cut:
they produce the one thing the brief says it cannot assess from a description — a goal →
real discovery → saved artifact → replay chain with evidence for both runs, and a log that
says *why*.

1. Task 0 (hygiene, 10 minutes) → Task 1 → Task 2 → Task 3 → Task 4 → **Task 11 Steps 1–2**
2. Task 8 → Task 6 → Task 7 (the multi-tenant and recoverable-condition evidence)
3. Task 9 → Task 5 → Task 10
4. Task 11 Steps 3–5 (write-up last, against whatever evidence actually landed)

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
  Baseline is 147 passing tests in ~0.25s (unverified in the audit environment — confirm the
  number in Task 0 Step 1 before relying on the "+N" counts below); that speed is a feature —
  do not add a test that needs Playwright.
- A `click` that times out for any reason other than a reported pointer interception is
  **never** retried. `tests/test_replay.py::test_click_timeout_is_not_retried` must keep
  passing unchanged.
- `timeout_ms` stays `> 0` and `<= 30000`.
- Run every `pytest` command from the repository root with the project venv active
  (`source .venv/bin/activate`).

---

## File Structure

| File | Change |
|---|---|
| `tests/conftest.py` | New — autouse fixture redirecting `cli.EVIDENCE_ROOT` to `tmp_path`. |
| `automation/models.py` | Add `CapabilityArtifact.derived_from`. |
| `automation/catalog.py` | `list()` exposes `derived_from`. |
| `automation/discovery.py` | `declare_outcome` tool; automatic `url_matches` checkpoint on `navigate`; events carry redacted arguments, results, model text, typed error names; stop screenshot; `vendor_product` parameter. |
| `automation/surface.py` | New `ActionBlocked(TimeoutError)`; `_invoke` raises it on "intercepts pointer events". Remove the stray section marker; move the Playwright imports to the top. |
| `automation/replay.py` | `_apply_tenant` rebases `navigate` URLs onto `TenantProfile.base_url`; `_act` recovers from `ActionBlocked` on click/fill/select; `tenant_version_drift` event. |
| `automation/policy.py` | `allow_dev_origins` defaults to `False`. |
| `automation/cli.py` | `_policy()` takes `allow_dev`; `--allow-dev-origins` on `discover`, `replay`, `capabilities invoke`; `--vendor-product` on `discover`. |
| `automation/evidence.py` | `screenshot_path` returns a repo-relative path when possible. |
| `automation/handoff.py` | Remove the stray `# ponytail:` token from the comment. |
| `tests/fakes.py` | `FakeSurface` gains `block_once_on` (raises `ActionBlocked` once). |
| `legacy/base/index.html` | New — vendor-default variant, generic control names, version 4.2. |
| `legacy/variant_b/index.html` | New — the current NorthStar-branded variant, moved from `legacy/index.html`, version 4.3. |
| `evidence/artifacts/legacy_product_lookup.json` | v3: accessible-name locators, fallbacks, checkpoints, a `product_not_found` outcome, no explicit consent step. |
| `evidence/artifacts/{prepare_product_checkout,register_test_account,delete_test_account}.json` | Checkpoints on every state-changing step; one declared fallback each; `derived_from` set. |
| `evidence/artifacts/discovered/` | New — raw, unedited artifacts as discovery saved them. |
| `config/tenants/legacy_variant.json` | v2: `base_url` port 8001, `product_version` 4.3, overrides for the four renamed controls. |
| `config/legacy_product_lookup.notfound.inputs.json` | New — the not-found input. |
| `config/policy.json` | Add the `127.0.0.1:8001` dev-only origin. |
| `tests/test_models.py`, `test_discovery.py`, `test_replay.py`, `test_cli.py`, `test_policy.py`, `test_surface.py`, `test_evidence.py`, `test_catalog.py` | New tests per task. |
| `README.md`, `REPORT.md`, `decisions.md` | Updated in Task 11 against the new evidence. |

---

### Task 0: Tests stop writing into `evidence/`

**Audit finding.** `tests/test_cli.py` exercises `main([...])` for `replay`, `capabilities
invoke`, and `discover` with `PlaywrightSurface` and the runners monkeypatched, but not
`cli.EVIDENCE_ROOT`. `_replay` and `_discover` call `_inside(EVIDENCE_ROOT, ...)` and
`EvidenceWriter(...)`, which `mkdir`s under the real `evidence/`. On disk today: 194
directories under `evidence/`, 174 of them empty. Git does not track empty directories, so
nothing ships — but the first thing an evaluator does is run `pytest`, and the second is
open `evidence/`.

**Files:**
- Create: `tests/conftest.py`
- Delete: every empty directory directly under `evidence/`

- [ ] **Step 1: Record the baseline**

Run: `pytest -q`
Expected: all tests pass. Write the count down; every "+N" below is relative to it.

Run: `find evidence -mindepth 1 -maxdepth 1 -type d -empty | wc -l`
Expected: a number well above 100.

- [ ] **Step 2: Write the fixture**

Create `tests/conftest.py`:

```python
"""Shared fixtures. Keeps the offline suite from touching the real evidence tree."""
import pytest

import automation.cli as cli


@pytest.fixture(autouse=True)
def _evidence_root_in_tmp(tmp_path, monkeypatch):
    """CLI tests call main(); evidence they create must land under tmp_path."""
    monkeypatch.setattr(cli, "EVIDENCE_ROOT", str(tmp_path / "evidence"))
    yield
```

`tests/test_cli.py:209` already sets the same attribute for one test; leave it — an explicit
override inside a test is harmless and documents intent.

- [ ] **Step 3: Verify**

```bash
find evidence -mindepth 1 -maxdepth 1 -type d -empty -delete
pytest -q
find evidence -mindepth 1 -maxdepth 1 -type d -empty | wc -l
```

Expected: the suite passes with the baseline count, and the last command prints `0`.

- [ ] **Step 4: Stage**

```bash
git add tests/conftest.py
```

---

### Task 1: Artifact provenance becomes a lineage

**Audit finding.** All four shipped artifacts carry `provenance: "hand_authored"`, which
reads as "written by hand" rather than "reviewed derivative of a real discovery run." The
brief's through-line is *the model discovers → the artifact becomes a capability*, so the
link from a derivative back to its discovery must be machine-readable. Task 11 makes the link
inspectable by also keeping the raw discovered JSON on disk.

**Files:**
- Modify: `automation/models.py:164-195` (`CapabilityArtifact`)
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
Expected: PASS, baseline + 4.

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
page, and it must not add a step. It may name the step it belongs to (matching how the
shipped artifacts scope `product_not_found` to `submit_search`); otherwise it is
artifact-level and checked after every step.

**Files:**
- Modify: `automation/discovery.py:71-100` (`TOOLS`), `113-165` (`ArtifactRecorder`),
  `289-363` (`_execute`), `365-369` (`_call_parts`), `102-110` (`SYSTEM_PROMPT`)
- Test: `tests/test_discovery.py`

**Interfaces:**
- Consumes: `_condition_from(args)` and `BusinessOutcomeSpec` (already imported paths).
- Produces: `ArtifactRecorder.declare_outcome(code: str, condition: ConditionSpec,
  description: str = "", step_id: str | None = None) -> bool` — `False` when `step_id`
  names no recorded step. The artifact returned by `finish()` carries artifact-level
  outcomes in `business_outcomes`; step-scoped ones land on that step.

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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_discovery.py -k outcome -v`
Expected: FAIL — the runner returns `"Unknown tool."` and `business_outcomes` stays empty.

- [ ] **Step 3: Add the tool, the recorder method, and the branch**

In `automation/discovery.py`, add `BusinessOutcomeSpec` to the existing
`from automation.models import (...)` block.

Append to `TOOLS`, after the `checkpoint` entry:

```python
    _tool(
        "declare_outcome",
        "Record an expected business result the caller must know about — a "
        "'no such record' page, a permission denial, an expired session. This is "
        "not a failure and not a checkpoint: the condition describes a branch that "
        "is NOT true right now, so it is stored, never evaluated. Give step_id to "
        "scope it to the step whose result it describes.",
        {**_CONDITION["properties"],
         "code": {"type": "string",
                  "description": "snake_case outcome code, e.g. product_not_found."},
         "outcome_description": {"type": "string",
                                 "description": "What the caller should understand."},
         "step_id": {"type": "string",
                     "description": "Recorded step id, e.g. s03. Omit for artifact-wide."}},
        ["code", "kind"],
    ),
```

In `ArtifactRecorder.__init__`, after `self._outputs`:

```python
        self._outcomes: list[BusinessOutcomeSpec] = []
```

Add the method after `attach_checkpoint`:

```python
    def declare_outcome(self, code: str, condition: ConditionSpec, description: str = "",
                        step_id: str | None = None) -> bool:
        """Store an expected business branch. Never evaluated at record time.

        False when step_id names no recorded step; nothing is stored in that case.
        """
        outcome = BusinessOutcomeSpec(code=code, when=condition, description=description)
        if step_id is None:
            self._outcomes.append(outcome)
            return True
        index = next((i for i, s in enumerate(self._steps) if s.id == step_id), -1)
        if index < 0:
            return False
        step = self._steps[index]
        self._steps[index] = step.model_copy(
            update={"business_outcomes": [*step.business_outcomes, outcome]})
        return True
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
                step_id = args.get("step_id")
                if not isinstance(code, str) or not code.strip():
                    return "Invalid tool arguments."
                if step_id is not None and not isinstance(step_id, str):
                    return "Invalid tool arguments."
                try:
                    condition = _condition_from(args)
                except (KeyError, TypeError, ValueError):
                    return "Invalid tool arguments."
                recorded = self._recorder.declare_outcome(
                    self._safe_text(code.strip()), condition,
                    self._safe_text(str(args.get("outcome_description") or "")),
                    step_id,
                )
                if not recorded:
                    return "No recorded step has that id. Omit step_id or use one you recorded."
                return f"Recorded business outcome {code.strip()}."
```

In `_call_parts`, add `"declare_outcome"` to the accepted-name set.

Finally, extend `SYSTEM_PROMPT` with one rule, placed before the `complete` rule:

```
- When a step could legitimately end differently — no such record, permission denied,
  session expired — call declare_outcome once for that branch, naming the step it
  belongs to. It is a result the caller needs, not a failure.
```

`_condition_from` ignores the extra `code`, `outcome_description`, and `step_id` keys, so it
needs no change.

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: PASS, previous count + 4.

- [ ] **Step 5: Stage**

```bash
git add automation/discovery.py tests/test_discovery.py
```

---

### Task 3: Every recorded navigation carries a checkpoint, and the model is told to checkpoint transitions

**Audit finding.** The three successful discovery runs on disk produced artifacts with no
`expect` on any step (the shipped derivatives were hand-decorated afterwards). Two causes:
`SYSTEM_PROMPT` never tells the model to call `checkpoint`, and the `checkpoint` tool
description ("Assert an expected page state") does not say it attaches to the step just
taken. The v1 plan proposed retro-attaching checkpoints to earlier steps by `step_id`; that
is withdrawn (see "What changed from v1").

**Approach.** A `navigate` step's post-condition is known the moment it succeeds: the URL
path the surface landed on. Record it automatically as a `url_matches` checkpoint — it was
observed true, it is deterministic, and it costs the model nothing. Clicks that transition
still need the model to say what "worked" looks like, so the prompt now requires it.

**Files:**
- Modify: `automation/discovery.py:97` (the `checkpoint` tool), `102-110`
  (`SYSTEM_PROMPT`), `132-144` (`record`), `304-313` (the `navigate` branch of `_execute`)
- Test: `tests/test_discovery.py`

**Interfaces:**
- Produces: `ArtifactRecorder.record(..., expect: ConditionSpec | None = None)`.
- Produces: `automation.discovery._url_checkpoint(url: str) -> ConditionSpec`.

- [ ] **Step 1: Write the failing tests**

Add `import re` to the top of `tests/test_discovery.py` if it is not already there, then:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_discovery.py -k "checkpoint" -v`
Expected: FAIL — `AttributeError: 'NoneType' object has no attribute 'kind'` for the first
test; the prompt test fails because the word is absent.

- [ ] **Step 3: Implement**

At module level in `automation/discovery.py`, add `import re` and, after `_condition_from`:

```python
def _url_checkpoint(url: str) -> ConditionSpec:
    """The post-condition of a navigation: the path it landed on, query and fragment free."""
    path = urlsplit(url).path or "/"
    return ConditionSpec(kind="url_matches", pattern=re.escape(path) + r"([?#].*)?$")
```

In `ArtifactRecorder.record`, add an `expect` keyword and pass it through:

```python
    def record(self, action: str, *, url: str | None = None, target: LocatorSpec | None = None,
               value_from_input: str | None = None, output_name: str | None = None,
               output_type: str | None = None, rationale: str = "",
               expect: ConditionSpec | None = None) -> Step:
        self._counter += 1
        step = Step(
            id=f"s{self._counter:02d}", action=action, url=url, target=target,
            value_from_input=value_from_input, output_name=output_name,
            locator_rationale=rationale, expect=expect,
        )
```

In the `navigate` branch of `_execute`, replace the `record` call:

```python
                self._recorder.record(
                    "navigate", url=url,
                    expect=_url_checkpoint(self._surface.current_url()),
                )
```

Replace the `checkpoint` tool entry in `TOOLS`:

```python
    _tool(
        "checkpoint",
        "Assert an expected page state and attach it to the step you just took, so "
        "replay can verify that step worked. Call it after every click that changes "
        "the page.",
        dict(_CONDITION["properties"]), ["kind"],
    ),
```

Add one rule to `SYSTEM_PROMPT`, before the `complete` rule:

```
- After every click that changes the page, call checkpoint with a condition that proves
  the change happened. Navigations are checkpointed for you.
```

`attach_checkpoint` already replaces `expect` on the last step, so an explicit checkpoint
after a navigate overrides the automatic one — that is the second test.

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: PASS, previous count + 3. `test_navigation_artifact_keeps_replay_url_while_messages_strip_query_and_fragment`
must still pass — it asserts on `steps[0].url`, which is unchanged.

- [ ] **Step 5: Stage**

```bash
git add automation/discovery.py tests/test_discovery.py
```

---

### Task 4: Discovery evidence records arguments, results, model text, and error types

**Audit finding.** `events.jsonl` for a discovery run holds only `{ts, type, tool, turn}` —
no arguments, no chosen locator, no tool result, no model text, no screenshot on stop. §3.5
asks for "a structured log of what the agent did **and why**" and "at least one richer signal
on failure"; both are absent from discovery. This is not hypothetical:
`evidence/discovery-aa0cef.../` escalated with the model reporting that every
`element_visible` condition returned "Invalid tool arguments", and nothing in the log can
confirm or refute it. (The `_condition_from` bug that caused it was fixed later —
`test_element_condition_kind_is_not_used_as_locator_kind` guards it — but the log could not
have told you.) Separately, `except Exception: return None` in `run()` collapses any bug into
`reason="external_error"`.

**Files:**
- Modify: `automation/discovery.py:220` (the `tool_call` event), `267` (the result append),
  `269-273` (the message append), `275-280` (the `run()` handlers), `360-363` (the
  `_execute` catch-all)
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
    events = [json.loads(l) for l in (tmp_path / "run-d" / "events.jsonl").read_text().splitlines()]
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
    events = [json.loads(l) for l in (tmp_path / "run-d" / "events.jsonl").read_text().splitlines()]
    stopped = next(e for e in events if e["type"] == "discovery_stopped")
    assert stopped["reason"] == "external_error"
    assert stopped["error_type"] == "RuntimeError"
    assert "connection reset" not in json.dumps(events)
    assert len(surface.screenshots) == 1
    assert stopped["screenshot"] == surface.screenshots[0]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_discovery.py -k "arguments or models_own or error_type" -v`
Expected: FAIL — `KeyError: 'args'`, `StopIteration` (no `model_text` event), and
`KeyError: 'error_type'`.

- [ ] **Step 3: Implement**

Replace the `tool_call` event in `run()`:

```python
                    self._evidence.event("tool_call", tool=self._safe_text(name or ""),
                                         turn=turn, args=self._safe_data(args or {}))
```

`_safe_data` already redacts strings and strips URL query/fragment; `EvidenceWriter.event`
then applies key-name and value redaction on top, so a secret cannot survive either path.

Replace the final dispatch line in `run()` (`results.append(self._result(call, self._execute(name, args)))`):

```python
                    text = self._execute(name, args)
                    self._evidence.event("tool_result", tool=name, turn=turn,
                                         result=self._safe_text(text)[:500])
                    results.append(self._result(call, text))
```

Immediately after `calls = [...]` in `run()`, before the `if not calls:` check, record the
model's prose:

```python
                for block in response.content:
                    if getattr(block, "type", "") == "text" and getattr(block, "text", ""):
                        self._evidence.event("model_text", turn=turn,
                                             text=self._safe_text(block.text)[:1000])
```

Add a helper to `DiscoveryRunner` (next to `_safe_text`):

```python
    def _stop_screenshot(self) -> str | None:
        """Richer failure signal for a stopped run. Never lets evidence capture mask the stop."""
        try:
            return self._surface.screenshot(
                self._evidence.screenshot_path("stopped"), mask=self._masks)
        except Exception:
            return None
```

Replace the two `except` handlers at the end of `run()`:

```python
        except _DiscoveryStopped as stopped:
            self._evidence.event("discovery_stopped", reason=stopped.reason,
                                 screenshot=self._stop_screenshot())
            return None
        except Exception as exc:
            self._evidence.event("discovery_stopped", reason="external_error",
                                 error_type=type(exc).__name__,
                                 screenshot=self._stop_screenshot())
            return None
```

Replace the catch-all in `_execute`:

```python
        except Exception as exc:
            self._evidence.event("action_error", tool=name,
                                 error_type=type(exc).__name__)
            raise _DiscoveryStopped("action_error") from None
```

Deliberately record the exception *type* and not its message: a Playwright error message
can quote page content, and page content is untrusted and may carry PII.

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: PASS, previous count + 3. `test_external_client_errors_stop_discovery_without_exposing_the_error`
must still pass — the message is still never written.

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
  (`build_parser`), `150-154` (`_policy`), `185` and `233` (the call sites)
- Test: `tests/test_cli.py`, `tests/test_policy.py`

**Interfaces:**
- Produces: `automation.cli._policy(path: str, allow_dev: bool) -> PolicyEngine` — the
  second argument is now required at every call site.

**Known collateral.** `tests/test_policy.py::_engine` builds an engine with a `dev_only`
loopback origin and `test_lookback_origin_requires_matching_port` expects port 8000 to pass.
After the flip, that helper must pass `allow_dev_origins=True` explicitly. Do that; do not
restore the old default.

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
def test_dev_origins_are_off_unless_the_flag_is_given():
    args = build_parser().parse_args([
        "replay", "--artifact", "a.json", "--inputs", "i.json"])
    assert args.allow_dev_origins is False
    args = build_parser().parse_args([
        "replay", "--artifact", "a.json", "--inputs", "i.json", "--allow-dev-origins"])
    assert args.allow_dev_origins is True
    assert build_parser().parse_args([
        "capabilities", "invoke", "x", "--args", "{}", "--allow-dev-origins",
    ]).allow_dev_origins is True


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

Add `from automation.policy import PolicyDenied` to `tests/test_cli.py`'s imports (it
already imports `Policy, PolicyEngine`).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_policy.py tests/test_cli.py -k dev -v`
Expected: FAIL — no `allow_dev_origins` attribute; `_policy()` takes one argument.

- [ ] **Step 3: Implement**

In `automation/policy.py`, flip the default so the safe value needs no caller cooperation:

```python
    def __init__(self, policy: Policy, allow_dev_origins: bool = False):
```

In `automation/cli.py`, add the flag to all three parsers that build an engine — `discover`,
`replay`, and `invoke`. Place this loop just before `return parser`, after `invoke` is fully
defined:

```python
    for parser_needing_dev in (discover, replay, invoke):
        parser_needing_dev.add_argument(
            "--allow-dev-origins", action="store_true",
            help="Permit origins marked dev_only in the policy file (local surfaces).")
```

Change `_policy`:

```python
def _policy(path: str, allow_dev: bool) -> PolicyEngine:
    try:
        return PolicyEngine(load_policy(path), allow_dev_origins=allow_dev)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValidationError):
        raise CliError("policy", "invalid file or fields") from None
```

Update both call sites (`_replay` and `_discover`) to
`_policy(args.policy, getattr(args, "allow_dev_origins", False))` — `getattr` because
`_capabilities` synthesises attributes on `args` for the invoke path.

In `tests/test_policy.py::_engine`, pass `allow_dev_origins=True` to the `PolicyEngine(...)`
call.

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: PASS, previous count + 3.

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
- Produces: `ReplayRunner._rebase(url: str | None) -> str | None` — swaps scheme and
  netloc for the tenant's, preserving path, query, and fragment. Policy still validates the
  result, so a tenant cannot rebase onto a disallowed origin.

**Known collateral.** `tests/test_replay.py:342` `test_tenant_profile_overrides_only_named_steps`
gives its profile `base_url="http://127.0.0.1:8000"` while the artifact navigates to
`automationexercise.com` under an engine that allows only that host. After rebasing, that
navigate would be denied. Change that test's `base_url` to
`"https://automationexercise.com"` — it tests locator overrides, not rebasing.

- [ ] **Step 1: Make `_runner` accept a policy, then write the failing tests**

`tests/test_replay.py:20` hardcodes `policy=_engine()`, so a test cannot supply its own.
Widen it first — every existing call keeps working:

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
    assert ("navigate", "https://evil.example.com/products") not in surface.actions


def test_no_tenant_leaves_navigation_untouched(tmp_path):
    surface = _happy_surface()
    _runner(surface, tmp_path).run(INPUTS)
    assert ("navigate", "https://automationexercise.com/products") in surface.actions
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_replay.py -k "rebas or tenant_profile" -v`
Expected: FAIL — the navigate action still targets `https://automationexercise.com/products`;
the rogue tenant run succeeds.

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
```

`moved` is computed **before** `model_copy` — after the copy the comparison is always false.

Update `test_tenant_profile_overrides_only_named_steps` per "Known collateral".

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: PASS, previous count + 3.

- [ ] **Step 5: Stage**

```bash
git add automation/replay.py tests/test_replay.py
```

---

### Task 7: A blocked interaction attempts interstitial dismissal — a timed-out one still does not

**Audit finding.** `recoveries` is `[]` in all ten checked-in runs, so the brief's middle
error category — recoverable conditions — has unit tests but no run-level evidence.
`_dismiss_interstitial` exists but fires only on `LocatorNotFound`. A consent overlay is the
canonical case, and an overlay does not hide the control underneath it: the locator resolves
fine and the *click* is what gets intercepted. So the real-world trigger never reaches the
recovery path.

**Why not "retry any click timeout"** (the v1 approach). `test_click_timeout_is_not_retried`
exists because a click that timed out may have been dispatched — Playwright's `click()` also
waits for navigations the click started — and re-clicking "Create Account" or "Delete" is
how automation double-submits. Playwright distinguishes the two cases in its call log: an
intercepted click never dispatches, and the timeout message says so ("`<div id="overlay">
intercepts pointer events`"). That report, and only that report, is a safe reason to retry.

**Files:**
- Modify: `automation/surface.py:23-24` (new exception), `116-127` (`_invoke`)
- Modify: `automation/replay.py:21` (import), `172-192` (`_act`)
- Modify: `tests/fakes.py:15-36, 60-70, 96-99` (`FakeSurface`)
- Test: `tests/test_surface.py`, `tests/test_replay.py`

**Interfaces:**
- Produces: `automation.surface.ActionBlocked(TimeoutError)` — raised by
  `PlaywrightSurface` when a Playwright timeout reports pointer interception.
- Produces: `FakeSurface(block_once_on=[...])` — raises `ActionBlocked` once for the named
  action, mirroring `fail_once_on`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_surface.py` (it already imports `surface_module` and `PlaywrightSurface`):

```python
def test_an_intercepted_click_is_reported_as_blocked_not_merely_timed_out():
    from automation.surface import ActionBlocked

    class Locator:
        def click(self, **kwargs):
            raise surface_module.PWTimeout(
                'locator.click: Timeout 3000ms exceeded.\nCall log:\n'
                '  - <div id="overlay">…</div> intercepts pointer events\n'
                '  - retrying click action')

    surface = PlaywrightSurface()
    surface._page = object()
    surface._resolve = lambda spec, timeout_ms: Locator()

    with pytest.raises(ActionBlocked):
        surface.click(None, 3000)
    assert issubclass(ActionBlocked, TimeoutError)


def test_a_plain_click_timeout_stays_a_timeout():
    from automation.surface import ActionBlocked

    class Locator:
        def click(self, **kwargs):
            raise surface_module.PWTimeout("locator.click: Timeout 3000ms exceeded.")

    surface = PlaywrightSurface()
    surface._page = object()
    surface._resolve = lambda spec, timeout_ms: Locator()

    with pytest.raises(TimeoutError) as caught:
        surface.click(None, 3000)
    assert not isinstance(caught.value, ActionBlocked)
```

In `tests/test_replay.py`:

```python
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


def test_a_timed_out_click_is_never_retried_even_with_an_interstitial_visible(tmp_path):
    surface = FakeSurface(url="https://automationexercise.com/", visible=["Accept"],
                          fail_once_on=["click"])
    result = _runner(surface, tmp_path).run(INPUTS)
    assert result.status == "failure"
    assert result.failure.error_code == "timeout"
    assert ("click", "Accept") not in surface.actions
```

Note on the first test: `block_once_on=["click"]` trips on the fixture's `submit_search`
step; `visible=["Accept"]` makes the interstitial resolvable; `_dismiss_interstitial` itself
calls `click`, which by then has consumed its one block, so the dismissal succeeds and the
retry goes through. The blocked click is never counted in `surface.actions` because the fake
raises before appending — hence `count(("click", "Search")) == 1`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_surface.py tests/test_replay.py -k "blocked or intercepted or never_retried" -v`
Expected: FAIL — `ImportError: cannot import name 'ActionBlocked'`, and
`TypeError: __init__() got an unexpected keyword argument 'block_once_on'`.

- [ ] **Step 3: Implement the surface side**

In `automation/surface.py`, after `UnexpectedDialog`:

```python
class ActionBlocked(TimeoutError):
    """The interaction never happened: another element intercepted the pointer.

    Distinct from a plain TimeoutError on purpose. A timed-out click may have
    fired and re-issuing it can double-submit; an intercepted click did not
    fire, which is what makes dismissing the interstitial and retrying safe.
    """
```

Change the `PWTimeout` branch of `_invoke`:

```python
        except PWTimeout as exc:
            self._raise_unexpected_dialog()
            if "intercepts pointer events" in str(exc):
                raise ActionBlocked(str(exc)) from None
            raise TimeoutError(str(exc)) from None
```

That phrase is Playwright's own call-log wording for actionability interception; it is the
one string this codebase matches on, and the surface test above is what pins it.

- [ ] **Step 4: Implement the fake**

In `tests/fakes.py`, import `ActionBlocked` alongside `LocatorNotFound`, then:

```python
    def __init__(self, url="https://automationexercise.com/", title="Home",
                 page_text="", visible=None, text_values=None, a11y="",
                 fail_once_on=None, block_once_on=None):
        ...
        self._fail_once_on = set(fail_once_on or ())
        self._block_once_on = set(block_once_on or ())
```

and extend `_trip`:

```python
    def _trip(self, action):
        if action in self._block_once_on:
            self._block_once_on.discard(action)
            raise ActionBlocked(f"<div> intercepts pointer events during {action}")
        if action in self._fail_once_on:
            self._fail_once_on.discard(action)
            raise TimeoutError(f"transient failure on {action}")
```

`click`, `fill`, and `navigate` already call `_trip`; add `self._trip("select")` as the first
line of `select` so all three interaction kinds can be blocked.

- [ ] **Step 5: Implement the replay side**

In `automation/replay.py`, extend the surface import:

```python
from automation.surface import ActionBlocked, LocatorNotFound, Surface, UnexpectedDialog
```

In `_act`, insert a new handler **before** the existing `except TimeoutError` (order
matters — `ActionBlocked` is a `TimeoutError`):

```python
        except ActionBlocked as exc:
            # The click never happened — Playwright reported that another
            # element intercepted it. That is the one timeout it is safe to
            # retry, and a known interstitial is the usual interceptor.
            # Bounded to one attempt.
            if (attempt == 1 and step.action in ("click", "fill", "select")
                    and self._dismiss_interstitial(step)):
                return self._act(step, values, outputs, attempt + 1)
            raise _Failure("timeout", f"step {step.id} to complete", str(exc))
```

Leave the `except TimeoutError` branch exactly as it is.

- [ ] **Step 6: Run the full suite**

Run: `pytest -q`
Expected: PASS, previous count + 5. `test_click_timeout_is_not_retried` unchanged and green.

- [ ] **Step 7: Stage**

```bash
git add automation/surface.py automation/replay.py tests/fakes.py tests/test_surface.py tests/test_replay.py
```

---

### Task 8: Two legacy variants, and a base artifact that runs un-overridden

**Audit finding.** This is the weakest requirement in the submission.
`legacy_product_lookup`'s base locators are placeholders — `button` matches any button,
`input#q` is a raw id — whose own rationales say "the tenant profile replaces this". The base
artifact therefore *cannot* run without overrides, which inverts the demonstration §3.7 asks
for: one reviewed flow, small per-tenant diff. There is also only one legacy page, so the
"variant" is a relabelling of the same file. And `success_condition` is `visible_text "Blue
Top"` — an input value hard-coded into the success condition.

**Approach.** Split the page into two variants of the same vendor product, differing exactly
the way two tenants of one vendor differ: same structure and flow, different control names,
branding, version, and host. `legacy/base/index.html` keeps generic vendor-default names at
version 4.2; `legacy/variant_b/index.html` keeps the NorthStar branding at version 4.3. The
artifact is recorded against base and runs there unmodified; the tenant profile carries a
`base_url` on a second port (Task 6), four locator overrides, and `product_version: "4.3"`
so Task 10's drift event fires on the tenant run. The consent overlay stays in both and is
*not* a step — Task 7's recovery handles it, which is what puts a real `RecoveryRecord` in
evidence.

**Files:**
- Create: `legacy/base/index.html`, `legacy/variant_b/index.html`,
  `config/legacy_product_lookup.notfound.inputs.json`
- Delete: `legacy/index.html` (its content becomes `variant_b`)
- Modify: `evidence/artifacts/legacy_product_lookup.json` (→ v3),
  `config/tenants/legacy_variant.json` (→ port 8001, version 4.3),
  `config/policy.json` (add the 8001 dev-only origin)
- Test: `tests/test_replay.py` (artifact-shape assertions only — no browser)

- [ ] **Step 1: Create the two variants**

`legacy/variant_b/index.html` is the current `legacy/index.html` moved (`git mv`) with one
edit: the chrome cell reads
`NorthStar Servicing Console 4.3 &mdash; Catalog Enquiry`. Everything else stays — nested
tables, no test IDs, the `Accept` overlay, `Item Lookup` / `Find Item` / `Item Description`
/ `Amount Due`, the fixed two-item catalog, the `No products found` branch.

`legacy/base/index.html` is the same file with the vendor-default names and title. Change
exactly these six strings and nothing structural:

| variant_b | base |
|---|---|
| `<title>NorthStar Servicing Console</title>` | `<title>Servicing Console</title>` |
| `NorthStar Servicing Console 4.3 &mdash; Catalog Enquiry` | `Servicing Console 4.2 &mdash; Catalog Enquiry` |
| `<label for="q">Item Lookup</label>` | `<label for="q">Product Search</label>` |
| `<button onclick="lookup()">Find Item</button>` | `<button onclick="lookup()">Search</button>` |
| `aria-label="Item Description"` | `aria-label="Product Name"` |
| `aria-label="Amount Due"` | `aria-label="Total"` |

Keep `<span role="heading" aria-level="2" ...>` in both — the accessible heading role is what
makes the surface reachable without a clean DOM, and it is the point the REPORT argues.

- [ ] **Step 2: Rewrite the artifact to v3**

`evidence/artifacts/legacy_product_lookup.json`: `artifact_version: 3`, six steps become
five (the `dismiss_consent` step is removed), every locator becomes an accessible name with a
structural fallback, every navigate/click step gains a checkpoint or an outcome, and the
not-found branch becomes a declared outcome. `submit_search` gets `timeout_ms: 3000` so the
overlay interception is reported in three seconds rather than ten. The steps:

```json
[
  {"id": "start", "action": "navigate", "url": "http://127.0.0.1:8000/",
   "expect": {"kind": "element_visible",
              "target": {"primary": {"kind": "label", "value": "Product Search"}}}},

  {"id": "search", "action": "fill", "value_from_input": "product",
   "target": {"primary": {"kind": "label", "value": "Product Search"},
              "fallback": {"kind": "css", "value": "input#q"}},
   "locator_rationale": "The field is labelled, so the label is the portable primary; the id is a structural fallback for a variant that drops the label association."},

  {"id": "submit_search", "action": "click", "timeout_ms": 3000,
   "target": {"primary": {"kind": "role_name", "role": "button", "name": "Search"}},
   "locator_rationale": "The only button in the lookup row exposes its visible text as its accessible name.",
   "business_outcomes": [
     {"code": "product_not_found",
      "when": {"kind": "visible_text", "text": "No products found"},
      "description": "The catalog has no item under that name."}],
   "expect": {"kind": "element_visible",
              "target": {"primary": {"kind": "role_name", "role": "heading", "name": "Product Name"}}}},

  {"id": "read_name", "action": "extract", "output_name": "product_name",
   "target": {"primary": {"kind": "role_name", "role": "heading", "name": "Product Name"}},
   "locator_rationale": "The result heading exposes an accessible name even though the markup is a span in a nested table."},

  {"id": "read_total", "action": "extract", "output_name": "amount_due",
   "target": {"primary": {"kind": "label", "value": "Total"}},
   "locator_rationale": "aria-label supplies the accessible name; the surrounding table cells carry no semantics."}
]
```

Replay evaluates business outcomes before the checkpoint, so on a not-found search
`submit_search` returns `product_not_found` before its `expect` can fail.

Set the header fields:

```json
  "target": {"vendor_product": "servicing_console", "base_url": "http://127.0.0.1:8000",
             "supported_versions": "4.2"},
  "success_condition": {"kind": "element_visible",
                        "target": {"primary": {"kind": "role_name", "role": "heading",
                                               "name": "Product Name"}}},
  "provenance": "hand_authored",
  "derived_from": null,
  "model_id": "none",
```

Keep `discovery_run_id: "manual-legacy-product-lookup"`. This artifact has no discovery
source and Task 1's validator permits `derived_from: null`.

- [ ] **Step 3: Rewrite the tenant profile, add the not-found inputs, widen the dev policy**

`config/tenants/legacy_variant.json`:

```json
{
  "tenant_id": "northstar_variant_b",
  "base_url": "http://127.0.0.1:8001",
  "product_version": "4.3",
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
    "submit_search": {"kind": "element_visible",
                      "target": {"primary": {"kind": "role_name", "role": "heading",
                                             "name": "Item Description"}}}
  }
}
```

`config/legacy_product_lookup.notfound.inputs.json`:

```json
{
  "product": "No Such Item"
}
```

In `config/policy.json`, add to `allowed_origins`:

```json
    {"scheme": "http", "host": "127.0.0.1", "port": 8001, "dev_only": true}
```

- [ ] **Step 4: Write the artifact-shape test**

In `tests/test_replay.py` — add `import json`, `from pathlib import Path`, and
`CapabilityArtifact` to its `automation.models` import. Anchor on the test file, not the
cwd:

```python
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

# the declared business outcome, on base
python -m automation.cli replay --allow-dev-origins \
  --artifact evidence/artifacts/legacy_product_lookup.json \
  --inputs config/legacy_product_lookup.notfound.inputs.json

# the policy default, without the flag
python -m automation.cli replay \
  --artifact evidence/artifacts/legacy_product_lookup.json \
  --inputs config/legacy_product_lookup.inputs.json

kill %1 %2
```

Expected: runs 1 and 2 both `status: "success"` with `product_name` / `amount_due`; run 2's
events contain `tenant_override` lines with `rebased_url` and (after Task 10) one
`tenant_version_drift` line; run 3 `status: "business_outcome"`,
`outcome_code: "product_not_found"`; run 4 `status: "failure"`,
`error_code: "policy_origin_denied"`. Runs 1–3 each carry one `interstitial_dismissed`
recovery from the consent overlay. If they do not, the overlay is not intercepting the
`Search` click — check that Task 7's `ActionBlocked` is raised (look for `action_error` or
`timeout` in events) before changing the artifact. Note that `fill` succeeds under the
overlay (Playwright's fill does not require pointer reception), so the recovery lands on
`submit_search`, not `search`.

Delete the four run directories that Task 0's fixture would not have caught here — this
step runs the real CLI — **except** the ones you want to keep as evidence: keep one of each
of runs 1, 2, 3, 4 and delete any retries.

- [ ] **Step 6: Stage**

```bash
git add legacy config/tenants/legacy_variant.json config/policy.json \
        config/legacy_product_lookup.notfound.inputs.json \
        evidence/artifacts/legacy_product_lookup.json tests/test_replay.py \
        evidence/replay-legacy_product_lookup-*
git rm --cached legacy/index.html 2>/dev/null || true
```

---

### Task 9: Checkpoints and fallbacks on the three public artifacts

**Audit finding.** One `expect` across 19 checkout steps; 17 consecutive steps proceed
without verifying the click worked, which is why an early break surfaces as a late
`locator_not_found` (`evidence/replay-prepare_product_checkout-ed63cd...` fails at s05 with
no evidence of what s04 did). The glossary calls this out by name. Separately,
`LocatorSpec.fallback` is implemented and unit-tested but used by zero shipped locators.

**Rule.** Every `navigate` and every `click` carries an `expect`, unless the step carries a
business outcome (the outcome *is* the verification) or is `requires_human` (a person
verified the state). `fill`/`select` steps do not need one; their effect is verified by the
checkpoint on the submit that follows. The guard test below enforces exactly this rule, so
the table below covers exactly the steps it flags.

**Do not change any primary locator that has replayed successfully.** Add fallbacks only.
A primary that is unproven on the live site is drift introduced by the fix.

**Files:**
- Modify: `evidence/artifacts/prepare_product_checkout.json` (→ v5),
  `evidence/artifacts/register_test_account.json` (→ v4),
  `evidence/artifacts/delete_test_account.json` (→ v5)
- Test: `tests/test_models.py`

- [ ] **Step 1: Add the checkpoints**

`prepare_product_checkout` — add `expect` to these steps (s04 and s18 carry outcomes; s20
already has one):

| step | action | `expect` |
|---|---|---|
| s01 | navigate / | `{"kind": "url_matches", "pattern": "automationexercise\\.com/?([?#].*)?$"}` |
| s02 | navigate /products | `{"kind": "url_matches", "pattern": "/products([?#].*)?$"}` |
| s05 | click View Product | `{"kind": "url_matches", "pattern": "/product_details/"}` |
| s07 | click Add to cart | `{"kind": "visible_text", "text": "Added!"}` |
| s08 | click View Cart | `{"kind": "url_matches", "pattern": "/view_cart([?#].*)?$"}` |
| s13 | navigate /view_cart | `{"kind": "url_matches", "pattern": "/view_cart([?#].*)?$"}` |
| s14 | click Proceed To Checkout | `{"kind": "visible_text", "text": "Register / Login"}` |
| s15 | click Register / Login | `{"kind": "url_matches", "pattern": "/login([?#].*)?$"}` |
| s19 | navigate /view_cart | `{"kind": "url_matches", "pattern": "/view_cart([?#].*)?$"}` |

`register_test_account` — add to s01 (`navigate /login`):
`{"kind": "url_matches", "pattern": "/login([?#].*)?$"}`; to s04 (`click Signup`):
`{"kind": "visible_text", "text": "Enter Account Information"}`; to s05 (`click Mr.` — a
radio, same page): `{"kind": "element_visible", "target": {"primary": {"kind": "role_name",
"role": "textbox", "name": "Password *"}}}`. s18 already has one.

`delete_test_account` — add to s01 (`navigate /login`):
`{"kind": "url_matches", "pattern": "/login([?#].*)?$"}`. s04 and s05 already have
checkpoints.

Do **not** put prose in a condition's `expected` field. Two shipped conditions currently use
`expected` as a comment ("On the checkout/order review page", "Redirected to the account
created page.", "Authenticated session confirmed after login", "Deletion confirmation is
visible ..."). `expected` is the comparison value for `value_equals`; on other kinds it is
ignored by `conditions.evaluate`, which is exactly why it reads as a schema smell. Delete
those four values while you are in the files.

- [ ] **Step 2: Add one honest fallback per artifact**

Only add a fallback that can resolve *uniquely* — `_resolve` treats "matched several" as
"matched none", so an ambiguous fallback is worse than no fallback.

- `prepare_product_checkout` s03: keep the primary `{"kind": "placeholder", "value":
  "Search Product"}`; add fallback `{"kind": "css", "value": "#search_product"}` and set
  `locator_rationale` to *"The search box exposes its placeholder as its accessible name;
  the id is the structural fallback for a variant that renders the placeholder
  differently."*
- `register_test_account` s06: keep the primary `{"kind": "role_name", "role": "textbox",
  "name": "Password *"}`; add fallback `{"kind": "css", "value":
  "input[data-qa=\"signup-password\"]"}` with rationale *"The labelled field is the
  portable primary; the vendor's test id is a fallback for a variant that relabels it."*
- `delete_test_account` s04: keep the primary `{"kind": "role_name", "role": "button",
  "name": "Login"}`; add fallback `{"kind": "css", "value":
  "button[data-qa=\"login-button\"]"}` with the same rationale shape.

Note the direction: the accessible name is the primary and the test ID is the *fallback*.
Several existing steps (s16–s18 in checkout, s02–s03 in register and delete) have the test
ID as primary with a rationale; leave them — they have replayed successfully — and let
REPORT §2 say plainly that they are the honest exception, not the rule.

- [ ] **Step 3: Set `derived_from` and bump versions**

On each of the three, keep `provenance: "hand_authored"` and add:

| artifact | `derived_from` | new `artifact_version` |
|---|---|---|
| `prepare_product_checkout` | `discovery-e4e5dc356f484e87b62933aa0b84ba1a` | 5 |
| `register_test_account` | `discovery-13cca73621aa405b818c44398e093bfb` | 4 |
| `delete_test_account` | `discovery-09beb9662dce4374841ceb672a352cd2` | 5 |

- [ ] **Step 4: Write the guard test**

In `tests/test_models.py` — add `import json` and `from pathlib import Path`:

```python
SHIPPED = sorted((Path(__file__).resolve().parents[1] / "evidence" / "artifacts").glob("*.json"))


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


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: p.stem)
def test_no_shipped_condition_uses_expected_as_a_comment(path):
    artifact = CapabilityArtifact(**json.loads(path.read_text()))
    conditions = [artifact.success_condition,
                  *(s.expect for s in artifact.steps if s.expect),
                  *(o.when for s in artifact.steps for o in s.business_outcomes),
                  *(o.when for o in artifact.business_outcomes)]
    assert all(c.expected is None for c in conditions if c.kind != "value_equals")
```

`SHIPPED` picks up `evidence/artifacts/discovered/*.json` only if you glob recursively —
it does not, on purpose: raw discovered artifacts (Task 11) are evidence, not shipped
capabilities, and are not held to the checkpoint rule.

- [ ] **Step 5: Run the suite**

Run: `pytest -q`
Expected: PASS, previous count + 12 (three parametrised tests × four artifacts). If the
first test fails for an artifact, add the missing checkpoint — do not weaken the assertion.
`tests/test_catalog.py::test_checked_artifacts_match_the_approved_capability_contracts`
must still pass: it pins names, inputs, outputs, and outcome codes, none of which change.

- [ ] **Step 6: Stage**

```bash
git add evidence/artifacts tests/test_models.py
```

---

### Task 10: Version drift is reported, and generation leftovers are removed

**Audit finding.** `TargetSpec.supported_versions` is read by no code;
`TenantProfile.product_version` is read by no code; `automation/surface.py:48` carries
`# --- appended to automation/surface.py ---` and `automation/handoff.py:141` begins
`# ponytail:` — both read as generation leftovers; `TargetSpec.vendor_product` is hardcoded
to `"automationexercise"` in `discovery.py:160` regardless of target; checked-in evidence
embeds absolute `/Users/aryanmamidwar/...` paths.

**Decision.** `product_version` and `supported_versions` are worth keeping: they are the hook
a drift check reads, and REPORT §4 owes §3.7 a drift answer. Make them earn their place by
having the runner emit an event when they disagree — reported, never fatal — and make Task
8's tenant run actually trigger it (base 4.2, variant B 4.3).

**Files:**
- Modify: `automation/replay.py:54-58` (`run`, after `run_started`),
  `automation/surface.py:48-51`, `automation/handoff.py:141`,
  `automation/discovery.py:116-126,160,173-194`, `automation/cli.py:42-50,231-237`,
  `automation/evidence.py:42-43`
- Test: `tests/test_replay.py`, `tests/test_evidence.py`, `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_replay.py` (it now imports `json` from Task 8):

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
```

In `tests/test_evidence.py` (add `from pathlib import Path`):

```python
def test_screenshot_paths_in_evidence_are_relative_to_the_repository(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    writer = EvidenceWriter(tmp_path, "run-x", set())
    assert not Path(writer.screenshot_path("failure")).is_absolute()
```

In `tests/test_cli.py`, extend `test_discovery_marks_environment_inputs_sensitive_and_infers_booleans`
by adding `"--vendor-product", "servicing_console"` to its `main([...])` argument list and
one assertion at the end:

```python
    assert captured["vendor_product"] == "servicing_console"
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_replay.py tests/test_evidence.py tests/test_cli.py -k "drift or relative or infers_booleans" -v`
Expected: FAIL — no `tenant_version_drift` event; `screenshot_path` returns an absolute path
when `root` is absolute; argparse rejects `--vendor-product`.

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

In `EvidenceWriter.screenshot_path`, return a repo-relative path when the run directory is
under the working directory:

```python
    def screenshot_path(self, label: str) -> str:
        path = self.run_dir / f"{next(self._counter):03d}-{label}.png"
        try:
            return str(path.relative_to(Path.cwd()))
        except ValueError:
            return str(path)
```

`tests/test_evidence.py::test_screenshot_paths_are_unique_and_inside_the_run` keeps passing:
its `tmp_path` is not under the cwd, so the absolute branch is taken.

In `automation/surface.py`, delete the line
`# --- appended to automation/surface.py -------------------------------------` and move the
three `playwright.sync_api` imports up into the module's import block at the top (after the
`pydantic` import). `MAX_A11Y_CHARS` stays where it is.

In `automation/handoff.py:141`, drop the stray token so the comment reads
`# A timed-out terminal read cannot be cancelled portably; daemonizing keeps ...`.

In `automation/discovery.py`, stop hardcoding the vendor. `ArtifactRecorder.__init__` gains
`vendor_product: str = "automationexercise"` (store it as `self._vendor_product`) and
`finish` uses it: `target=TargetSpec(vendor_product=self._vendor_product,
base_url=self._base_url)`. `DiscoveryRunner.__init__` gains the same keyword and passes it
through to `ArtifactRecorder(...)`.

In `automation/cli.py`, add to the `discover` parser:

```python
    discover.add_argument("--vendor-product", default="automationexercise",
                          help="Vendor product name recorded in the artifact's target.")
```

and pass `vendor_product=args.vendor_product` in `_discover`'s `DiscoveryRunner(...)` call.

- [ ] **Step 4: Run the suite**

Run: `pytest -q`
Expected: PASS, previous count + 3.

Then: `grep -rn "ponytail\|appended to automation" automation/` — no matches.

- [ ] **Step 5: Stage**

```bash
git add automation tests
```

---

### Task 11: Live evidence refresh and write-up alignment

**Audit finding.** Two claims in the submission outrun their evidence: no artifact was
emitted by discovery (`provenance: "discovered"` appears nowhere on disk — the discovered
JSON was overwritten by the hand edits, so the derivation cannot be diffed), and the flagship
`prepare_product_checkout` has never replayed successfully under its current contract —
three business-outcome/failure runs, zero successes, while the historical "successes" used a
superseded contract with exploratory outputs. Tasks 1–10 make both fixable; this task
produces the evidence and makes the prose match it. Section 4 of the brief is explicit:
"the discovery run has to be real ... we can't assess a description of it."

**Files:**
- Create: `evidence/artifacts/discovered/<name>.json`, new `evidence/discovery-*` and
  `evidence/replay-*` directories
- Modify: `README.md`, `REPORT.md`, `decisions.md`

- [ ] **Step 1: Produce a genuinely discovered artifact and keep it raw**

With `ANTHROPIC_API_KEY`, `AE_EMAIL`, `AE_PASSWORD` loaded per the README:

```bash
name="lookup_product_$(date +%Y%m%d%H%M%S)"
python -m automation.cli discover \
  --goal "Search for Blue Top on the products page and read its name and price. If the search returns no products, declare that as a business outcome. Checkpoint each page change." \
  --capability "$name" \
  --description "Read a product's name and price from the products listing." \
  --inputs config/inputs.example.json
mkdir -p evidence/artifacts/discovered
cp "evidence/artifacts/$name.json" "evidence/artifacts/discovered/$name.json"
python -m automation.cli replay \
  --artifact "evidence/artifacts/$name.json" \
  --inputs config/inputs.example.json
```

Accept it only if the saved artifact has `provenance: "discovered"`, a non-empty
`business_outcomes` (artifact-level or on a step), and at least one `expect` on a click —
navigations get theirs automatically (Task 3), so an artifact whose only checkpoints are on
navigations means the model ignored the prompt rule. If the model does not call
`declare_outcome` or `checkpoint`, tighten the tool descriptions or the prompt rule and run
again; do not hand-edit the artifact. Keep the discovery directory of the accepted run and
the failed attempts' directories too (they are evidence that the tooling was iterated,
which the brief values), but name only the accepted one in REPORT.

The copy under `evidence/artifacts/discovered/` is **never edited**. If you later review and
improve this artifact, the improved version is a new `hand_authored` artifact whose
`derived_from` names this run — that is the lineage Task 1 built.

`git diff --no-index evidence/artifacts/discovered/$name.json evidence/artifacts/$name.json`
must be empty at submission unless you deliberately created a derivative.

- [ ] **Step 2: Land a successful checkout replay**

```bash
python -m automation.cli replay \
  --artifact evidence/artifacts/prepare_product_checkout.json \
  --inputs config/inputs.example.json
```

Expected: `status: "success"` with `product_name`, `unit_price`, `cart_total`. If a
checkpoint from Task 9 fails, the checkpoint is wrong about the site — fix the checkpoint
text or pattern, not by deleting it, and record what was wrong in `decisions.md`. If the
capability genuinely cannot pass, demote it in REPORT §3 and make `register_test_account`
the headline slice explicitly; do not leave the flagship unproven and unmentioned.

- [ ] **Step 3: Rewrite the claims that changed**

`REPORT.md` — the brief asks for ~1–3 pages under seven fixed headings and the current file
is already at the top of that range. Every addition below must be paid for by a cut; the
evidence table at the top is the first candidate to move into `README.md`.

- §2 — provenance is now a lineage: name the newly discovered artifact and its raw copy
  under `evidence/artifacts/discovered/`, and state that the three public artifacts are
  reviewed derivatives that point at their source run via `derived_from`. State the
  boolean-output convention (`false` is unrepresentable; a negative business fact is a
  business outcome). Say that test-ID primaries on login fields are the documented exception
  to accessible-name-first.
- §3 — cite the new checkout success; keep the retained failed run as historical evidence;
  cite the legacy base run's `interstitial_dismissed` recovery as the recoverable-condition
  evidence; delete the sentence conceding the current checkout contract has no successful
  replay once Step 2 lands. Name the three-way `ActionBlocked` / `TimeoutError` /
  `LocatorNotFound` distinction as the mechanism behind "retry only when the click never
  happened".
- §4 — this section changes most. Replace "This is not a claim of same-artifact
  cross-variant reuse" with what is now true: one artifact, two variants, `base_url`
  rebasing plus four locator overrides and two condition overrides, and cite both runs.
  Add the drift answer §3.7 asks for: `supported_versions` vs. `product_version` compared
  per run, emitted as `tenant_version_drift`, reported and never fatal, with the variant B
  run as the example — and say what the production version would add (a per-tenant replay
  canary and a stability signal), since that is a cut, not a claim.
- §5 — discovery stops now carry a screenshot; one sentence.
- §6 — `dev_only` origins are now denied unless `--allow-dev-origins` is passed. Say that
  `_deletes_account` keyword matching is a backstop, not the risk model: risk belongs on the
  artifact step, reviewed by a human.
- §7 — update the cuts list; remove the items this plan delivered; add the two "deliberately
  not in this plan" items below.

`README.md`:
- Add `--allow-dev-origins` to the offline legacy commands and serve two directories on
  ports 8000 and 8001, showing the un-overridden base run, the tenant run, and the
  not-found run (copy the block from Task 8 Step 5, wrapped in the existing subshell/trap
  pattern).
- Add `--vendor-product` to the discover example.
- Refresh the "Evidence" bullet list to the new run directories; move the REPORT evidence
  table here if §3 cuts it.

`decisions.md`: append numbered decisions continuing from 22, each with the alternatives and
why, for: `derived_from` lineage plus a raw discovered copy over a flat provenance enum
(Task 1/11); `declare_outcome` as a record-only tool that is never evaluated (Task 2);
automatic navigation checkpoints and no retro-attachment (Task 3, including why the v1
`step_id` idea was rejected); tenant rebasing limited to scheme+netloc with the path treated
as flow (Task 6); recovery on reported interception only, never on a plain click timeout
(Task 7); two legacy variants over one relabelled page (Task 8); accessible name as primary
with the test ID as fallback, proven primaries left alone (Task 9); version drift reported
and never fatal (Task 10). Add a Change History line dated 2026-09-11.

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
- **Committing and pushing.** Deliverable 1 is a public GitHub repo; the local history has
  two commits and a large staged tree. Aryan commits manually; this plan only stages.
  Decide separately whether `docs/superpowers/` belongs in a public submission — the brief
  assumes AI-assisted development and rewards visible reasoning, so shipping the spec and
  plans is defensible, but `.superpowers/` (already ignored) is not.

## Verification

Run all of these before calling the work done. Aryan commits; do not.

1. `pytest -q` — green, and still under a second. Expect roughly baseline + 40 tests.
2. `find evidence -mindepth 1 -maxdepth 1 -type d -empty | wc -l` after `pytest` — `0`.
3. `python -m automation.cli capabilities list` — works with no API key; every entry shows
   `derived_from`, and at least one shows `provenance: "discovered"`.
4. Legacy base, **no** `--tenant`: `status: "success"` with both outputs, and one
   `interstitial_dismissed` recovery. This is the assertion that failed before Task 8.
5. Legacy variant B, same artifact plus `--tenant`: `status: "success"`, events show
   `tenant_override` with `rebased_url` and one `tenant_version_drift`.
6. Legacy, unknown product: `status: "business_outcome"`, `outcome_code:
   "product_not_found"`.
7. Loopback replay **without** `--allow-dev-origins`: `status: "failure"`,
   `error_code: "policy_origin_denied"`.
8. One live `discover` run whose saved artifact has `provenance: "discovered"`, non-empty
   business outcomes, and at least one `expect` on a click; an identical raw copy under
   `evidence/artifacts/discovered/`; then a replay of that artifact unchanged.
9. `prepare_product_checkout` replay: `status: "success"` with all three declared outputs.
10. A discovery `events.jsonl` from Task 11 contains `tool_call` lines with `args`,
    `tool_result` lines, and at least one `model_text` line; `grep -c REDACTED` on it is
    consistent with the number of sensitive fills, and neither `AE_EMAIL`'s nor
    `AE_PASSWORD`'s value appears anywhere under `evidence/`.
11. `grep -rn "ponytail\|appended to automation" automation/` — no matches.
12. `grep -rln "/Users/aryanmamidwar" evidence/` — no matches in newly written runs.
13. `wc -w REPORT.md` — not materially above today's count; the brief said 1–3 pages.
14. Re-read REPORT §§2, 3, 4, 6 line by line against the evidence directories. Any sentence
    without a run behind it is either cut or moved to §7.
