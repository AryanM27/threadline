# Computer-Use Automation System Design

## Objective

Build a reproducible Python vertical slice that uses Claude to discover three workflows on the public Automation Exercise practice site, saves each successful workflow as a typed capability artifact, and replays those artifacts through Playwright without model decisions. The system must enforce safety policy, classify runtime outcomes, capture evidence, and transfer the same live browser session to a human before deleting an account.

The three capabilities are:

1. `register_test_account`
2. `prepare_product_checkout`
3. `delete_test_account`

Only synthetic data may be used. Checkout stops on the review page; the system never submits payment or places an order.

## Architecture

The application is a single-process Python 3.12 command-line program. This keeps browser state, recording, policy enforcement, and handoff control in one process and avoids infrastructure that does not improve the evaluated workflow.

Discovery and replay share four components:

- `PolicyEngine` validates domains, routes, action types, and risk before an action and verifies the URL again after navigation.
- `PlaywrightSurface` owns one headed Chromium context and implements observation, semantic locator resolution, actions, extraction, checkpoints, and screenshots.
- `EvidenceWriter` writes redacted JSON Lines events and screenshots under `evidence/`.
- Pydantic models validate artifacts, runtime inputs, interventions, events, and results at trust boundaries.

Discovery adds a `DiscoveryRunner` that calls Claude with a fixed set of custom tools. Claude observes the current page, chooses an allowed action, and declares when the goal is complete or blocked. `ArtifactRecorder` stores only successful, replayable actions and assertions; it does not store the raw model transcript.

Replay replaces Claude and the recorder with `ReplayRunner`. It validates the artifact and supplied inputs, then executes the saved steps in order using the same policy engine and Playwright surface.

`TerminalHandoff` implements control ownership as `AUTOMATION -> PAUSED -> HUMAN -> AUTOMATION`. It never creates a second browser context.

## Discovery Tools and Data Flow

Claude receives only these custom tools:

- `observe()` returns the current URL, title, a bounded page/accessibility summary, and a screenshot.
- `navigate(url)` opens an allowlisted URL.
- `click(target)` activates a semantic target.
- `fill(target, value_from_input)` retrieves a named runtime input locally and fills it. Claude does not need the secret value.
- `select(target, value_from_input)` selects a runtime value.
- `extract(name, target, output_type)` declares and captures an output.
- `checkpoint(condition)` verifies an expected state.
- `complete(success_condition)` ends a successful discovery.
- `escalate(reason)` creates an intervention request when Claude cannot proceed safely.

Each mutating tool call follows this sequence:

1. Validate the requested action and current URL against policy.
2. Resolve the target using the declared semantic locator.
3. Execute the action with a bounded timeout.
4. Verify any declared post-action checkpoint.
5. Validate the resulting URL against policy.
6. Record the replayable action and redacted evidence.

Runtime values are passed by input name, such as `password`, rather than embedded in tool arguments. The recorder writes `value_from_input: "password"`, never the value itself. Non-sensitive goal text is sent to Claude; passwords and other fields marked sensitive remain in local runtime memory.

The discovery loop stops on success, escalation, 30 model turns, 10 minutes, policy denial, or a hard tool failure.

## Artifact Schema

`CapabilityArtifact` contains:

- `schema_version`: exactly `"1.0"` for this implementation.
- `name` and `description`: the calling contract.
- `target`: vendor/product identifier and allowed base URL.
- `inputs`: named `InputSpec` objects with type, required flag, sensitivity, and validation constraints.
- `outputs`: named `OutputSpec` objects with type and extraction source.
- `steps`: ordered `Step` objects.
- `success_condition`: the final checkpoint.
- `business_outcomes`: known conditions and their stable result codes.

Each `Step` contains:

- `id`: stable and unique within the artifact.
- `action`: `navigate`, `click`, `fill`, `select`, `extract`, or `assert`.
- `target`: omitted only for navigation; otherwise a `LocatorSpec`.
- `value_from_input`: optional runtime input reference.
- `output_name`: required for extraction.
- `expect`: optional post-action `ConditionSpec`.
- `timeout_ms`: positive and capped at 30,000.
- `risk`: `safe` or `requires_human`.

`LocatorSpec` has one primary locator and at most one explicit fallback. Supported locator kinds are `role_name`, `label`, `placeholder`, `text`, and `css`. Replay tries the primary locator first and uses the fallback only when the primary finds no unique visible element. CSS is allowed only when the public surface lacks a reliable semantic locator. Coordinates and session-local element references are forbidden in saved artifacts.

`ConditionSpec` supports `url_matches`, `visible_text`, `element_visible`, `element_absent`, and `value_equals`. Conditions are data, not executable code.

Unknown fields and unsupported schema versions fail validation. Artifacts cannot contain arbitrary JavaScript, Python, or generated selectors.

### Capability Contracts

`register_test_account` accepts synthetic identity and address fields, including `email` and sensitive `password`. It returns `account_created: bool` and succeeds when `ACCOUNT CREATED!` is visible. An already-registered email is a `business_outcome` with code `email_already_registered`.

`prepare_product_checkout` accepts sensitive `email` and `password`, `product`, and integer `quantity >= 1`. It returns `product_name`, `unit_price`, and `cart_total`. It succeeds on the checkout review page. No payment data is accepted. An absent product returns `product_not_found`; rejected credentials return `authentication_failed`.

`delete_test_account` accepts sensitive `email` and `password`. The deletion action is marked `requires_human`. It returns `account_deleted: bool` and succeeds when `ACCOUNT DELETED!` is visible. A denied intervention returns `cancelled_by_human`.

## Deterministic Replay and Error Handling

Replay never imports or calls the Anthropic client. It executes validated steps through `PlaywrightSurface` with a fixed viewport, pinned Chromium revision, bounded waits, and explicit checkpoints.

Each step produces one of four internal classifications:

- `success`: the action and checkpoint completed.
- `business_outcome`: an expected result meaningful to the caller, such as `product_not_found`.
- `recoverable`: a known cookie/ad interstitial was dismissed once or a navigation/load timeout was retried once.
- `hard_failure`: an unexpected domain, ambiguous/missing locator after fallback, unexpected dialog, invalid artifact, or failed checkpoint after permitted recovery.

The external `RunResult` status is `success`, `business_outcome`, or `failure`. Successful recovery is represented in the event log and recovery metadata on a success result rather than as a fourth terminal status.

A failure result contains the run ID, capability name, step ID/index, stable error code, expected state, bounded observed-state summary, and evidence paths. The runner captures a screenshot before returning failure. It never blindly continues after an unclassified state.

## Safety

The checked-in policy permits only `https://automationexercise.com` and `https://www.automationexercise.com`. Navigation, current URL, and redirect destinations are checked by parsed scheme and exact hostname; substring matching is forbidden. The allowed actions are the six artifact actions plus observation and checkpoint operations.

Page content is untrusted data. Instructions found in the page never change the system prompt, policy, tool definitions, or goal. Claude cannot request shell commands, arbitrary JavaScript, downloads, file access, payment submission, or navigation outside the allowlist.

Account deletion always requires human control. Order placement and payment submission are forbidden rather than approvable.

Secrets are accepted from an ignored local input file or environment at runtime. A recursive redactor replaces fields marked sensitive and common secret keys before serialization. Screenshots are taken only at defined checkpoints; password fields remain masked. Raw Claude request/response bodies and raw DOM snapshots are not persisted.

## Human Escalation and Handoff

Before a `requires_human` step, or when discovery explicitly escalates, automation stops issuing actions and creates an `InterventionRequest` containing run/capability/step IDs, reason, current URL, bounded observed state, and a before screenshot.

The terminal requests an operator name and confirmation. On acceptance, control state changes to `HUMAN`, and the same headed Chromium window remains available for manual interaction. For deletion, the human performs the delete action in that window, enters a short description of what they did, and presses Enter to return control. The system records the operator name, description, timestamps, URLs, and before/after screenshots. It then changes ownership to `AUTOMATION` and verifies the artifact checkpoint.

Declining or terminating the handoff does not execute deletion and returns `cancelled_by_human`. A handoff timeout returns a failure with preserved evidence.

## Heterogeneous Surfaces and Multi-Tenant Reuse

The implemented `PlaywrightSurface` conforms to a narrow conceptual contract: `observe`, `act`, `extract`, and `snapshot`. The artifact describes logical actions, locators, and conditions rather than Playwright code. A later legacy-web or desktop adapter can map the same contract to accessibility-tree controls or screenshot coordinates. Coordinate locators would require a future schema version because they have different replay guarantees.

For multi-tenant use, a base artifact would be keyed by vendor product and supported version range. A tenant profile would supply base URL and detected product/version metadata. A small tenant override could replace only a named locator or condition; it would not fork the whole artifact. The implementation will document this structure but will not build a tenant registry or override service.

Locator or checkpoint failures become drift signals containing the tenant profile, observed app version when available, current URL, and screenshot. Unattended execution of the affected artifact/tenant combination should be disabled until review rather than automatically relearned.

## Testing

Offline pytest tests use a `FakeSurface` and scripted Claude responses. They cover:

- artifact validation, schema-version rejection, and parameter constraints;
- exact-host domain validation, action/risk policy, and recursive redaction;
- conversion of successful discovery tool calls into parameterized steps without secret values;
- deterministic replay success and typed output extraction;
- `product_not_found` and authentication business outcomes;
- one permitted retry followed by success;
- hard failure after a missing locator or failed checkpoint;
- deletion handoff acceptance, denial, control-state transitions, and evidence metadata.

Tests require neither an API key nor network access. Public-site discovery and replay are documented integration demonstrations, not part of the default test command.

## Evidence and Demonstration

The checked-in `evidence/` directory contains:

- three artifacts created by genuine Claude discovery runs;
- redacted JSONL logs for all three discovery runs;
- redacted JSONL logs for deterministic replay of all three artifacts with a second synthetic account;
- a replay using an unknown product that returns `product_not_found`;
- failure or recovery evidence for a simulated/observed transient condition;
- before/after screenshots and the operator action record for deletion handoff.

The README provides exact commands for environment setup, browser installation, live discovery, artifact replay, offline tests, and a no-API-key replay using checked-in artifacts. Evidence metadata records pinned dependency/model versions and the run timestamp so reviewers can distinguish public-site drift from local nondeterminism.

## Repository Structure

```text
README.md
REPORT.md
pyproject.toml
requirements.txt
config/policy.json
automation/
  __init__.py
  cli.py
  models.py
  policy.py
  surface.py
  discovery.py
  replay.py
  evidence.py
  handoff.py
tests/
  test_models.py
  test_policy.py
  test_discovery.py
  test_replay.py
  test_handoff.py
evidence/
  artifacts/
  discovery/
  replay/
  screenshots/
```

The runtime dependencies are the Anthropic Python SDK, Playwright, and Pydantic. Pytest is the only test dependency. The CLI uses the standard library `argparse`; logging and JSON Lines output use the standard library.

## Delivery Schedule

Day 1 establishes the typed contracts, policy/redaction, Playwright surface, and offline tests. Day 2 builds and tests the Claude discovery/recording loop and records the first successful capability. Day 3 builds deterministic replay, error handling, and terminal handoff, then records success and exceptional evidence. Day 4 is reserved for reproducibility testing from a clean environment, the required README and seven-section REPORT, evidence curation, and final review.

## Deliberate Cuts

This submission excludes payment/order submission, a remote operator dashboard, true co-browsing, desktop automation, tenant infrastructure, queues, services, databases, replay-time LLM recovery, automatic artifact approval, and optional stretch goals. These should be added only after the core record/replay contract is proven stable.

## References

- [Automation Exercise test cases](https://www.automationexercise.com/test_cases)
- [Claude tool-use overview](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview)
- [Claude computer and browser tool guidance](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-combinations)
