# Computer-Use Automation System Design

## Objective

Build a reproducible Python vertical slice that uses Claude to discover three workflows on the public Automation Exercise practice site, saves each successful workflow as a typed capability artifact, and replays those artifacts through Playwright without model decisions. The system must enforce safety policy, classify runtime outcomes, capture evidence, and transfer the same live browser session to a human before deleting an account.

Claude perceives every surface through its accessibility tree rather than its DOM. A second, deliberately hostile local lookup surface — nested-table layout, no test IDs, non-semantic markup, and an overlay — exercises that choice with a separate hand-authored artifact. It demonstrates the tenant-profile substitution seam, but is not evidence that the public checkout artifact ran unchanged against a second tenant.

The three capabilities are:

1. `register_test_account`
2. `prepare_product_checkout`
3. `delete_test_account`

Only synthetic data may be used. Checkout stops on the review page; the system never submits payment or places an order.

## Architecture

The application is a single-process Python 3.12 command-line program. This keeps browser state, recording, policy enforcement, and handoff control in one process and avoids infrastructure that does not improve the evaluated workflow.

Discovery and replay share four components:

- `PolicyEngine` provides exact origin/route, action, and risk checks. Replay brackets every action with live-current and resulting-URL validation; discovery validates the current URL before non-navigation actions, the requested navigation destination, and the resulting URL.
- `PlaywrightSurface` owns one headed Chromium context and implements accessibility-tree observation, semantic locator resolution, actions, extraction, checkpoints, and screenshots.
- `EvidenceWriter` writes redacted JSON Lines events and screenshots under `evidence/`.
- Pydantic models validate artifacts, runtime inputs, interventions, events, and results at trust boundaries.

Discovery adds a `DiscoveryRunner` that calls Claude with a fixed set of custom tools. Claude observes the current page, chooses an allowed action, and declares when the goal is complete or blocked. `ArtifactRecorder` stores only successful, replayable actions and assertions; it does not store the raw model transcript.

Replay replaces Claude and the recorder with `ReplayRunner`. It validates the artifact and supplied inputs, optionally applies a tenant profile, then executes the saved steps in order using the same policy engine and Playwright surface.

`TerminalHandoff` implements control ownership as `AUTOMATION -> PAUSED -> HUMAN -> AUTOMATION`. It never creates a second browser context. Both discovery and replay can enter it.

`CapabilityCatalog` exposes the saved artifacts as callable tool schemas so an agent can list and invoke them by name.

## Perception Model

Claude never receives the DOM or a screenshot. `observe()` returns only the current URL, title, and a bounded accessibility snapshot taken through Playwright's accessibility API. Screenshots are captured through a separate evidence operation at defined failures, checkpoints, and handoffs; no image tokens are added to discovery.

This is a structural constraint rather than a stylistic one. Because Claude only ever sees accessible roles, names, and values, it can only describe a target in terms the accessibility tree exposes; it cannot invent a CSS selector from markup it has not been shown. The recorded locator is therefore accessibility-shaped by construction, not by convention.

The accessibility tree is also the representation that survives the environment the system is designed for. It is available on legacy server-rendered pages that have no test IDs, and operating systems expose the equivalent tree for native desktop applications. A DOM-first design would have to be rewritten for those surfaces; this one does not.

The cost is accepted deliberately. An accessibility snapshot is noisier than a DOM query, and some controls on real pages carry weak or missing accessible names. `css` therefore survives as a last resort, with the constraints described under `LocatorSpec`.

## Discovery Tools and Data Flow

Claude receives only these custom tools:

- `observe()` returns the current URL, title, and a bounded accessibility snapshot.
- `navigate(url)` opens an allowlisted URL.
- `click(target)` activates a semantic target.
- `fill(target, value_from_input)` retrieves a named runtime input locally and fills it. Claude does not need the secret value.
- `select(target, value_from_input)` selects a runtime value.
- `extract(name, target, output_type)` declares and captures an output.
- `checkpoint(condition)` verifies an expected state.
- `complete(success_condition)` ends a successful discovery.
- `escalate(reason)` creates an intervention request when Claude cannot proceed safely.

Each mutating tool call follows this sequence:

1. Validate the live current URL before a non-navigation action, and validate every requested action, risk, and navigation destination against policy.
2. Resolve the target using the declared semantic locator.
3. Execute the action with a bounded timeout.
4. Validate the resulting URL against policy.
5. Evaluate declared business outcomes, then verify any post-action checkpoint.
6. Record the replayable action and redacted evidence.

Runtime values are passed by input name, such as `password`, rather than embedded in tool arguments. The recorder writes `value_from_input: "password"`, never the value itself. Non-sensitive goal text is sent to Claude; passwords and other fields marked sensitive remain in local runtime memory.

The discovery loop stops on success, escalation, 60 model turns, 10 minutes, policy denial, or a hard tool failure. The turn budget is sized for the target's account-creation form, which has roughly fifteen fields and therefore consumes most of a smaller budget on `fill` calls alone.

## Artifact Schema

`CapabilityArtifact` contains:

- `schema_version`: exactly `"1.0"` for this implementation. This versions the format.
- `artifact_version`: an integer revision of this capability, incremented when the flow is re-recorded or edited. This versions the content.
- `created_at`, `discovery_run_id`, and `model_id`: provenance. A reviewer can trace any artifact back to the discovery run and model that produced it, and the run's redacted log is checked in under that ID.
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
- `business_outcomes`: optional conditions that terminate the run with a stable code at this step.
- `timeout_ms`: positive and capped at 30,000.
- `risk`: `safe` or `requires_human`.
- `locator_rationale`: a short note recording why this locator was chosen and what it degrades to. It is written at record time and carried for human review.

`LocatorSpec` has one primary locator and at most one explicit fallback. Supported locator kinds are ranked rather than interchangeable:

1. `role_name` and `label` are primary. Both are accessibility-tree concepts. They map without translation to Windows UI Automation and macOS accessibility control patterns, so a future desktop adapter reuses them unchanged.
2. `placeholder` and `text` follow. They are still content-derived and readable, but they are weaker: placeholders vanish once a field is filled, and visible text is the first thing tenant branding changes.
3. `css` is a last resort. It requires a populated `locator_rationale` explaining why no accessible name was available, and it is forbidden outright in artifacts recorded against the legacy surface, where markup-derived selectors are exactly the thing being argued against.

Replay tries the primary locator first and uses the fallback only when the primary finds no unique visible element. Coordinates and session-local element references are forbidden in saved artifacts.

`ConditionSpec` supports `url_matches`, `visible_text`, `element_visible`, `element_absent`, and `value_equals`. Conditions are data, not executable code.

Unknown fields and unsupported schema versions fail validation. Artifacts cannot contain arbitrary JavaScript, Python, or generated selectors.

### Capability Contracts

`email` and `password` are marked sensitive in all three capabilities. Marking an identifier sensitive in one capability and not another would produce evidence that redacts the same value in one log and prints it in the next, which defeats the purpose of the redactor.

`register_test_account` accepts synthetic identity and address fields, including sensitive `email` and `password`. It returns `account_created: bool` and succeeds when `ACCOUNT CREATED!` is visible. An already-registered email is a `business_outcome` with code `email_already_registered`; this is also the capability's validation-error case, since the site surfaces it as an inline form error rather than a failure.

`prepare_product_checkout` accepts sensitive `email` and `password`, `product`, and integer `quantity >= 1`. It returns `product_name`, `unit_price`, and `cart_total`. It succeeds on the checkout review page. No payment data is accepted. An absent product returns `product_not_found`; rejected credentials return `authentication_failed`; losing the authenticated session mid-flow returns `session_expired`.

`delete_test_account` accepts sensitive `email` and `password`. The deletion action is marked `requires_human`. It returns `account_deleted: bool` and succeeds when `ACCOUNT DELETED!` is visible. A denied intervention returns `cancelled_by_human`.

## Deterministic Replay and Error Handling

Replay never imports or calls the Anthropic client. It executes validated steps through `PlaywrightSurface` with a fixed viewport, pinned Chromium revision, bounded waits, and explicit checkpoints.

After each action, the runner evaluates conditions in a fixed order:

1. The step's declared `business_outcomes`, plus the artifact-level ones. A match terminates the run immediately with status `business_outcome` and that outcome's stable code.
2. The step's `expect` checkpoint.
3. Post-navigation policy validation.

Business outcomes are evaluated before the checkpoint deliberately. A "no such product" page will always fail the checkpoint that expected a product detail page, so checking the checkpoint first would report every legitimate business answer as a failure. That inversion is the specific mistake this ordering exists to prevent. Outcome conditions reuse `ConditionSpec` and need no separate evaluator.

Session expiry is modeled the same way: an artifact-level outcome whose condition matches the login page appearing after authentication was already established. It applies at every step of an authenticated flow rather than at one declared step.

Each step produces one of four internal classifications:

- `success`: the action and checkpoint completed.
- `business_outcome`: an expected result meaningful to the caller, such as `product_not_found`.
- `recoverable`: a known cookie/ad interstitial was dismissed once or a navigation/load timeout was retried once.
- `hard_failure`: an off-allowlist origin or denied route, ambiguous/missing locator after fallback, unexpected dialog, invalid artifact, or failed checkpoint after permitted recovery.

The external `RunResult` status is `success`, `business_outcome`, or `failure`. Successful recovery is represented in the event log and recovery metadata on a success result rather than as a fourth terminal status.

An unexpected dialog is classified as a `hard_failure` by choice, not by omission. A dialog the artifact did not anticipate is by definition an unmodeled state, and dismissing it blindly is how automation confirms something it was never authorized to confirm.

A failure result contains the run ID, capability name, step ID/index, stable error code, expected state, bounded observed-state summary, and evidence paths. The runner captures a screenshot before returning failure. It never blindly continues after an unclassified state.

When a `hard_failure` occurs in a run started with `--interactive`, the runner does not return immediately. It raises the same `InterventionRequest` used for `requires_human` steps and offers the operator control of the live session, so a replay that hits a condition it cannot recover from has the same escape hatch as a step known in advance to need a person. If the operator resolves the situation and hands control back, the runner re-evaluates the step's checkpoint and continues; if they decline, the run returns the failure result unchanged. Non-interactive runs — the production path an agent triggers — always return the failure result, since there is no operator to route to.

## Safety

The checked-in policy permits three origins: `https://automationexercise.com`, `https://www.automationexercise.com`, and `http://127.0.0.1:8000` for the local legacy surface. Navigation, current URL, and redirect destinations are checked by parsed scheme, exact hostname, and port; substring matching is forbidden. The allowed actions are the six artifact actions plus observation and checkpoint operations.

The local origin is a real widening of the policy surface and is treated as such. It is the only plaintext-HTTP entry, it is bound to the loopback interface rather than to `localhost` as a name, and it is marked `dev_only` in `config/policy.json` so it can be excluded by configuration rather than by code edit.

Policy also carries a route denylist evaluated on the parsed path, both before an action and after every navigation. Payment and order-submission routes are denied there. This is what makes "payment is forbidden rather than approvable" an enforced property instead of a described intention: there is no approval path that reaches those routes, because the engine rejects them before any risk classification is consulted.

Page content is untrusted data. Instructions found in the page never change the system prompt, policy, tool definitions, or goal. Claude cannot request shell commands, arbitrary JavaScript, downloads, file access, payment submission, or navigation outside the allowlist.

Account deletion always requires human control. Order placement and payment submission are forbidden rather than approvable.

Secrets are accepted from an ignored local input file or environment at runtime. A recursive redactor replaces fields marked sensitive and common secret keys before serialization. Screenshots are taken only at defined checkpoints, and sensitive fields are masked using Playwright's `mask` locator argument so the value is painted over before the image is encoded rather than blurred afterwards. Raw Claude request/response bodies and raw DOM snapshots are not persisted.

Redaction has a stated limit. Screenshots of a filled registration form necessarily show the identity and address values that were typed into it. Those values are synthetic by policy, and the system never accepts real credentials or real PII, but the images are not a redaction boundary and are not treated as one.

## Human Escalation and Handoff

Three conditions raise an intervention: a `requires_human` step is about to execute, discovery explicitly escalates, or an interactive replay hits a `hard_failure`. In all three cases automation stops issuing actions and creates an `InterventionRequest` containing run/capability/step IDs, reason, current URL, bounded observed state, and a before screenshot.

The terminal requests an operator name and confirmation. On acceptance, control state changes to `HUMAN`, and the same headed Chromium window remains available for manual interaction. For deletion, the human performs the delete action in that window, enters a short description of what they did, and presses Enter to return control. The system records the operator name, description, timestamps, URLs, and before/after screenshots. It then changes ownership to `AUTOMATION` and verifies the artifact checkpoint.

While control is `HUMAN`, automation issues no actions but keeps observing: it subscribes to the page's navigation events and records the URL trail the operator produced. This is passive and does not interfere with their work. It turns "what the human did" from a self-reported sentence alone into a self-reported sentence corroborated by a navigation record. It remains a summary rather than a full event stream, which is a documented limit of the terminal handoff.

Declining or terminating the handoff does not execute deletion and returns `cancelled_by_human`. A handoff timeout returns a failure with preserved evidence.

## Heterogeneous Surfaces and Multi-Tenant Reuse

The implemented `PlaywrightSurface` conforms to a narrow conceptual contract: `observe`, `act`, `extract`, and `snapshot`. The artifact describes logical actions, locators, and conditions rather than Playwright code. Because both `observe` and the primary locator kinds are already expressed in accessibility-tree terms, a desktop adapter maps `role_name` and `label` onto Windows UI Automation or macOS accessibility control patterns without a schema change; the seam is the surface contract, and the recorded flow does not know which surface satisfies it. Coordinate locators would still require a future schema version because they carry different replay guarantees.

### The legacy surface

`legacy/` is a static page served locally that imitates a legacy back-office screen: nested-table layout, no test IDs, non-semantic markup, and an interstitial overlay. The checked page has neither a frameset/iframe nor a confirmation dialog. It implements a lookup-only flow similar to part of checkout.

It is a separate, hand-authored `legacy_product_lookup` capability for the local NorthStar page. It makes one bounded claim falsifiable: semantic accessibility locators and the `TenantProfile` substitution mechanism operate on hostile layout markup. It does not prove that Automation Exercise and NorthStar are the same vendor product, or that one reviewed checkout artifact runs across both surfaces.

Its interactive controls do carry accessible names, through native `label` elements and `aria-label` attributes. This is not a softening of the exercise; it is what separates hostile *structure* from an inaccessible page. Layout markup is table soup with no test IDs and no semantic containers, which is what defeats CSS selectors, while the controls themselves remain nameable — the realistic legacy case, and the precondition that makes forbidding `css` on this surface achievable rather than a rule discovery would immediately have to break.

### Tenant reuse

A base artifact is keyed by vendor product and supported version range. A `TenantProfile` supplies `tenant_id`, `base_url`, detected product/version metadata when available, `locator_overrides` mapping a step ID to a replacement `LocatorSpec`, and `condition_overrides` mapping a step ID to a replacement `ConditionSpec`. Replay loads a profile passed with `--tenant` and substitutes the named locators and conditions before execution.

Conditions need overriding for the same reason locators do: a `visible_text` checkpoint asserts wording, and wording is the first thing a tenant rebrands.

An override replaces one named locator or condition; it never forks the artifact. That constraint is the point. Forking produces N artifacts that drift independently and must each be re-reviewed; overriding keeps one reviewed flow with a small, auditable diff per tenant, and makes the question "what is different about this tenant" answerable by reading a few lines.

The checked demonstration applies four locator overrides to the separate hand-authored `legacy_product_lookup` artifact and replays it successfully on the local page. The public `prepare_product_checkout` artifact is not reused: it has public entry URLs and a larger step topology. Full cross-variant reuse therefore remains future work requiring an explicit entry-URL/step-mapping design.

Locator or checkpoint failures remain structured hard failures with the current URL and screenshot evidence. The invoked tenant profile is known from the run inputs, and replay never relearns or changes it automatically.

## Capability Catalog

`CapabilityCatalog` renders each saved artifact's name, description, and typed inputs and outputs as a JSON tool schema, and invokes one by name with typed arguments. The CLI exposes `capabilities list` and `capabilities invoke <name> --args <json>`.

This is close to free: the artifact already carries the contract an agent needs, so the catalog is a projection of existing types rather than new modeling. It is included because the brief's framing is that an artifact is a capability an agent calls, and demonstrating an actual invocation by name is stronger evidence of that than describing it. Invocation runs the ordinary replay path; the catalog adds no execution authority of its own.

## Testing

Offline pytest tests use a `FakeSurface` and scripted Claude responses. They cover:

- artifact validation, schema-version rejection, provenance-field presence, and parameter constraints;
- exact-origin validation, rejection of an off-allowlist redirect encountered mid-flow, route-denylist rejection of a payment route, action/risk policy, and recursive redaction;
- rejection of a `css` locator that carries no `locator_rationale`;
- conversion of successful discovery tool calls into parameterized steps without secret values;
- deterministic replay success and typed output extraction;
- replaying one artifact twice against the fake surface yields an identical step trace;
- `product_not_found`, authentication, and `session_expired` business outcomes;
- business-outcome conditions being evaluated before the step checkpoint, so a not-found page reports an outcome rather than a checkpoint failure;
- one permitted retry followed by success;
- hard failure after a missing locator or failed checkpoint;
- a tenant profile substituting the correct locator and condition for the named steps and leaving others untouched;
- the catalog rendering an artifact's inputs and outputs as a tool schema, and rejecting an invocation whose arguments fail the artifact's input validation;
- deletion handoff acceptance, denial, control-state transitions, and evidence metadata;
- an interactive replay hard failure raising an intervention and transitioning control state.

Tests require neither an API key nor network access. Public-site discovery and replay are documented integration demonstrations, not part of the default test command.

## Evidence and Demonstration

The checked-in `evidence/` directory contains:

- three artifacts, each labelled in its provenance as discovered or hand-authored, under the floor stated in the delivery schedule;
- redacted JSONL logs for every discovery run performed;
- redacted JSONL logs for deterministic replay of all three artifacts with a second synthetic account;
- a replay using an unknown product that returns `product_not_found`;
- failure or recovery evidence for a simulated/observed transient condition;
- before/after screenshots and the operator action record for deletion handoff;
- a replay of the separate hand-authored legacy lookup artifact under a tenant profile, with the applied override events;
- the exported capability catalog and a log of one capability invoked by name with typed arguments.

The README provides exact commands for environment setup, browser installation, live discovery, artifact replay, offline tests, and a no-API-key replay using checked-in artifacts. Evidence metadata records pinned dependency/model versions and the run timestamp so reviewers can distinguish public-site drift from local nondeterminism.

`REPORT.md` uses these seven headings verbatim, in this order:

1. Architecture
2. Artifact schema
3. Determinism & error handling
4. Heterogeneity & multi-tenant
5. Escalation & handoff
6. Safety
7. Cuts

It opens with a table mapping each Section 3 requirement to the component and evidence file that satisfies it, since submissions are read side by side.

## Repository Structure

```text
README.md
REPORT.md
pyproject.toml
requirements.txt
config/policy.json
config/tenants/legacy_variant.json
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
  catalog.py
legacy/
  index.html
tests/
  test_models.py
  test_policy.py
  test_discovery.py
  test_replay.py
  test_handoff.py
  test_tenant.py
  test_catalog.py
evidence/
  artifacts/
  discovery/
  replay/
  screenshots/
```

The runtime dependencies are the Anthropic Python SDK, Playwright, and Pydantic. Pytest is the only test dependency. The CLI uses the standard library `argparse`; the legacy surface is served with `http.server`; logging and JSON Lines output use the standard library.

## Delivery Schedule

Day 1 establishes the typed contracts, policy/redaction, accessibility-tree surface, and offline tests. Day 2 builds and tests the Claude discovery/recording loop and records the first successful capability. Day 3 builds deterministic replay, error handling, and terminal handoff, then records success and exceptional evidence. Day 4 adds the legacy surface, tenant overrides, and capability catalog, then covers reproducibility testing from a clean environment, the required README and seven-section REPORT, evidence curation, and final review.

The requirement floor is one genuine LLM-driven discovery run against a live surface. Three are planned. If the public target, the schedule, or the API budget makes three impractical, `prepare_product_checkout` is the flagship discovery that must be genuine; the remaining artifacts are hand-authored against the same schema and labelled as such in both the artifact provenance and REPORT section 7. Silently presenting a hand-authored artifact as a discovered one is not an available option.

## Submission

The repository is pushed to a public GitHub repository. The repository URL is emailed on its own line to `assignments@interface.ai` from the address used to apply, with no attachment. The email is drafted for review and sent only after explicit approval, and commits remain manual.

## Deliberate Cuts

This submission excludes payment/order submission, a remote operator dashboard, true co-browsing, desktop automation, tenant registry or override services, queues, services, databases, replay-time LLM recovery, automatic artifact approval, artifact confidence scoring, code generation from artifacts, and multi-run stability reporting. These should be added only after the core record/replay contract is proven stable.

The capability catalog stretch goal is delivered by re-rendering the artifact's existing contract. A tenant-profile locator-substitution seam and a local lookup demonstration are delivered, but same-artifact cross-variant reuse is cut: the proof uses a separate hand-authored artifact and does not establish full public-checkout reuse.

## References

- [Automation Exercise test cases](https://www.automationexercise.com/test_cases)
- [Claude tool-use overview](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview)
- [Claude computer and browser tool guidance](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-combinations)
