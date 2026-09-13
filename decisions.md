# Computer-Use Automation System — Decision Log

This file preserves the project decisions made during planning, the alternatives considered, their pros and cons, and the questions and answers that led to each choice. It should be updated whenever a decision changes.

## Current Decision Summary

| Area | Decision | Status |
|---|---|---|
| Language | Python 3.12 | Accepted |
| Target type | Public demonstration website | Accepted |
| Target application | Automation Exercise | Accepted |
| Implemented workflows | Product lookup, cart review, checkout review, and account management including deletion | Accepted |
| Capability boundaries | `register_test_account`, `prepare_product_checkout`, and `delete_test_account` | Accepted |
| Discovery model | Claude through the Anthropic API | Accepted; replaces the earlier OpenAI choice |
| Browser automation | Custom typed Claude tools backed by Playwright | Accepted |
| Perception | Accessibility tree, never the DOM | Accepted; revises Decision 7 |
| Second surface | Local hostile/legacy lookup page with a tenant-profile demonstration | Accepted with bounded evidence claim |
| Replay | Deterministic Playwright execution with no model calls | Required |
| Replay escalation | An interactive hard failure offers the same live-session handoff | Accepted; revises Decision 13 |
| Tenant reuse | Built: locator overrides in a tenant profile | Accepted; revises Decision 16 |
| Stretch goals | Capability catalog and same-artifact legacy cross-variant reuse delivered | Implementation amendment to Decision 20 |
| Human handoff | Terminal handoff using the same visible Chromium session | Accepted |
| Risk boundary | Human performs account deletion; payment/order submission is forbidden | Accepted |
| Artifact | Typed, versioned, parameterized JSON with semantic locators | Accepted |
| Evidence | Artifacts, redacted JSONL logs, and failure/handoff screenshots | Accepted |
| Delivery target | A focused 3–4 day implementation | Accepted |
| Architecture | Single-process CLI with small internal modules | Accepted |

## Decision 1: Use Python

**Decision:** Implement the system in Python 3.12.

### Python

**Pros**

- The developer is more comfortable with Python.
- Both Anthropic and Playwright provide Python SDKs.
- Pydantic gives concise typed validation for artifacts and results.
- The standard library provides the CLI, JSON, logging, and file handling needed here.

**Cons**

- Playwright documentation and examples are sometimes more extensive in TypeScript.
- Browser automation callbacks and asynchronous APIs can feel more natural in Node.js.

### TypeScript/Node.js — rejected

**Pros**

- Playwright is native to the Node.js ecosystem.
- Strong compile-time typing for artifact and action schemas.
- Many browser automation examples use TypeScript.

**Cons**

- It is not the developer's preferred language.
- It would slow delivery without providing a meaningful assignment advantage.

## Decision 2: Use a Public Demo Site

**Decision:** Automate a public practice site instead of building a local mock banking application.

**Amended by Decision 18:** the public site is still the primary target, but it is no longer the only surface. A small local hostile page was added alongside it.

### Public demo site

**Pros**

- Stronger evidence that the system works against a UI the project does not control.
- Avoids making the automation artificially easy with custom test IDs or known markup.
- Requires less application-building work.
- Better demonstrates real navigation, waiting, locators, and external runtime behavior.

**Cons**

- The site can change, become slow, or go offline.
- Network access is required for live discovery and integration demonstrations.
- Reproducing injected errors and edge cases is harder.
- Terms, rate limits, advertisements, and shared state must be respected.

### Local mock banking app — rejected

**Pros**

- Fully controlled and repeatable.
- Directly matches the banking context.
- Makes validation errors, permission failures, timeouts, and dialogs easy to demonstrate.
- Has no external terms, rate-limit, availability, or real-data concerns.

**Cons**

- Adds application-building work unrelated to the automation engine.
- Can appear artificially easy because the author controls the markup.
- Provides weaker evidence of generalization to an unfamiliar application.

## Decision 3: Use Automation Exercise

**Decision:** Use [Automation Exercise](https://www.automationexercise.com/) as the public target.

### Automation Exercise

**Pros**

- It is explicitly intended for UI automation practice.
- It provides product search, product detail, cart, registration, login, checkout, and account deletion flows.
- It supports both successful and negative paths.
- The flow resembles the proxy e-commerce example in the assignment.
- Synthetic accounts can be created and deleted without real payment activity.

**Cons**

- It is an e-commerce site rather than banking software.
- It may contain advertisements or changing page behavior.
- It remains an external dependency that can drift.
- Shared public-site state can reduce repeatability.

### OrangeHRM — rejected

**Pros**

- It more closely resembles an enterprise back-office application.
- It creates a stronger analogy to internal banking administration software.
- It provides multi-step authenticated business workflows.

**Cons**

- Shared demo data and authentication are less predictable.
- The public instance may reset or change independently.
- The desired registration, checkout, and deletion scenario does not map naturally to HR workflows.
- It increases implementation risk within the time box.

### Why an e-commerce proxy is acceptable

The assignment does not require access to banking software. It explicitly permits a public proxy target and gives adding a product to a cart and reaching checkout review as an example. The submission must explain how the same artifact, policy, surface, and handoff boundaries extend to legacy web and desktop banking applications without pretending the target itself is a bank.

## Decision 4: Cover Product, Cart, Checkout, and Account Management

**Decision:** Cover the first four candidate workflows:

1. Product lookup
2. Cart review
3. Checkout review
4. Account management, including deletion

### Product lookup

**Pros**

- Demonstrates parameterized search and typed extraction.
- Provides product name, price, category, and availability data.
- Naturally supports `product_not_found` as a business outcome.

**Cons**

- It is too shallow to demonstrate the full system by itself.

### Cart review

**Pros**

- Adds multi-step navigation and reversible state changes.
- Enables quantity, unit price, and cart-total checkpoints.
- Does not require submitting a real order.

**Cons**

- The cart can depend on cookies and browser-session state.

### Checkout review

**Pros**

- Creates a realistic, non-trivial end-to-end path.
- Demonstrates authentication, address review, multiple checkpoints, and a clear stopping boundary.
- Matches the assignment's proxy example closely.

**Cons**

- Requires a synthetic account and more runtime inputs.
- Approaching payment increases safety risk if the stopping boundary is wrong.

**Guardrail:** Stop at checkout review. Never accept payment data, place an order, or submit payment.

### Account management with deletion

**Pros**

- Demonstrates registration, authentication, persistent state, and cleanup.
- Account deletion is a meaningful risky action for human approval and handoff.
- Deleting synthetic accounts helps keep repeated public-demo runs clean.

**Cons**

- Registration requires unique synthetic email addresses.
- Deletion is irreversible and cannot be left to unattended automation.
- Failed cleanup can leave public demo accounts behind.

### Other workflows considered but not selected

#### Contact request

**Pros:** Exercises multi-field forms and file upload.

**Cons:** Adds an independent capability without strengthening the central record/replay design; file upload broadens safety and data-handling scope.

#### Product review

**Pros:** Demonstrates an external write and irreversible action policy.

**Cons:** Publishes content to a public service and is unnecessary when deletion already exercises human approval.

#### Cross-session cart

**Pros:** Demonstrates persistence across login state.

**Cons:** Adds statefulness and flakiness that the selected checkout capability already covers sufficiently.

## Decision 5: Save Three Focused Capabilities

**Decision:** Produce three artifacts:

- `register_test_account`
- `prepare_product_checkout`
- `delete_test_account`

### Focused artifacts

**Pros**

- Each capability has a clear input/output contract.
- Registration and deletion are separated from the normal checkout preparation path.
- Failures are easier to locate and replay.
- Capabilities can be independently reviewed, approved, and invoked.
- Account setup and cleanup can be composed around the main business flow.

**Cons**

- The demo runs three commands instead of one.
- State and inputs must be passed consistently between capabilities.
- More than one artifact must be included in evidence.

### One large end-to-end artifact — rejected

**Pros**

- One command demonstrates the entire journey.
- No cross-capability state coordination is needed.

**Cons**

- It mixes account lifecycle operations with product checkout.
- It creates an oversized input contract.
- A failure late in the run forces repetition of unrelated earlier work.
- It is less reusable as an agent-invocable capability.

## Decision 6: Use Claude for Discovery

**Decision:** Use Claude through the Anthropic API for the live LLM-driven discovery loop.

### Claude

**Pros**

- Strong tool-use support in Python.
- Anthropic provides browser- and computer-use patterns for UI tasks.
- Custom tool calls can be constrained to a small typed action set.
- Tool results naturally support the repeated observe-decide-act loop.

**Cons**

- Discovery still has model variance and cannot be perfectly reproducible.
- API and model versions must be pinned and documented.
- A live discovery run requires the developer's API key and incurs API cost.

### OpenAI — initially selected, then replaced

**Pros**

- The Responses API supports computer use, screenshots, and custom tools.
- It provides strong structured tool calling and Python SDK support.
- It could implement the same bounded action interface.

**Cons**

- The proposed design required more custom browser-adapter work to obtain replay-friendly semantic actions.
- The team preferred Claude after comparing current browser-oriented guidance.

### Provider abstraction — deliberately omitted

**Pros if added:** The discovery model could be switched without changing the rest of the system.

**Cons now:** A provider interface with one implementation adds code and testing without helping the required demonstration. Replay is already provider-independent because it makes no model calls.

## Decision 7: Use Custom Typed Claude Tools Backed by Playwright

**Decision:** Claude may call only these bounded tools: `observe`, `navigate`, `click`, `fill`, `select`, `extract`, `checkpoint`, `complete`, and `escalate`. Playwright executes the requested UI operations.

**Amended by Decision 17:** the tool set is unchanged, but `observe` returns an accessibility snapshot rather than a page summary, and locator kinds are ranked rather than flat.

### Option B: Custom Claude tools + Playwright — selected

**Pros**

- Discovery actions directly use the same typed shape saved for replay.
- No conversion from temporary element references or coordinates is required.
- Policy checks can run before every action.
- Secret values can remain local and be referenced by input name.
- Scripted Claude responses make the discovery recorder testable offline.
- It provides the strongest reproducibility story.

**Cons**

- The observation and tool schemas must be designed and maintained.
- More agent-loop code is owned by the project.
- It looks less turnkey than using a provider-defined browser toolset.

### Option A: Claude browser-use toolset — rejected

**Pros**

- Provider-defined, page-aware browser operations.
- Element references are better than raw coordinates during discovery.
- Less custom tool description work.

**Cons**

- Element references are session-local and cannot be saved directly for replay.
- A translation step would be needed to produce durable semantic locators.
- Tool/model compatibility and a relatively new toolset increase version risk.

### Option C: Screenshot and coordinate computer use — rejected

**Pros**

- Closest to general computer use on legacy or desktop applications.
- Does not rely on a clean DOM.
- Provides strong visual evidence.

**Cons**

- Coordinates vary with viewport, fonts, banners, scrolling, and page layout.
- Deterministic replay would be fragile.
- A second reconciliation stage would be needed to derive stable locators.
- It is slower and riskier within 3–4 days.

## Decision 8: Optimize for Reproducibility at the Replay Boundary

**Decision:** Discovery may be stochastic, but it must produce a fixed artifact. Replay must then execute that artifact without Claude.

**Pros**

- Matches the assignment's intended model: the model discovers; the artifact becomes the reusable capability.
- Makes production execution cheaper and easier to debug.
- Checked-in artifacts can be replayed without an API key.
- Failures identify a specific recorded step, expectation, and observation.

**Cons**

- A changed public site can still invalidate recorded locators or checkpoints.
- Determinism does not mean guaranteed success against an unavailable external service.
- Discovery output must be reviewed before it is trusted.

### Reproducibility controls

- Pin Python dependencies, Claude model ID, and Chromium revision.
- Use a fixed viewport.
- Validate inputs and artifact schema before browser startup.
- Save semantic locators using role/name, label, placeholder, or visible text.
- Allow at most one declared locator fallback.
- Use explicit waits and post-action checkpoints.
- Save example artifacts and offline scripted discovery fixtures.
- Classify public-site drift as an observable failure instead of silently improvising.

## Decision 9: Use a Terminal Human Handoff

**Decision:** Pause automation and give the human control of the same visible Chromium session through a terminal-guided handoff.

### Terminal handoff

**Pros**

- It is the smallest real same-session handoff.
- Browser state, cookies, and navigation context remain intact.
- Control ownership can be recorded explicitly as `AUTOMATION -> PAUSED -> HUMAN -> AUTOMATION`.
- The operator can enter their name and summarize their manual action.
- Before/after screenshots provide clear evidence.

**Cons**

- It supports only an operator on the same machine.
- It does not provide remote co-browsing or an intervention queue.
- Human actions are documented through the operator summary and state snapshots rather than a full event stream.
- It is less visually polished than a dashboard.

### Web operator dashboard — rejected

**Pros**

- More polished and visually demonstrable.
- Could display intervention context, ownership, screenshots, and pending requests.
- Provides a foundation for remote or multi-operator workflows.

**Cons**

- Requires an additional server, frontend, state synchronization, and authentication model.
- A dashboard alone does not provide remote control of the browser.
- True co-browsing is explicitly outside the assignment scope.
- It adds failure points without materially improving the evaluated handoff mechanism.

## Decision 10: Treat Deletion as Human-Controlled and Payment as Forbidden

**Decision:** The human—not the automation—performs account deletion in the same browser. Payment and order submission cannot be approved and remain blocked.

### Human-controlled deletion

**Pros**

- Demonstrates a real intervention request and control transfer.
- Prevents unattended irreversible account changes.
- Gives the reviewer clear before/after evidence and an operator record.

**Cons**

- The deletion replay is not fully unattended.
- A person must be present to finish cleanup.

### Automated deletion — rejected

**Pros:** Faster and fully unattended.

**Cons:** Violates the chosen conservative treatment of irreversible actions and weakens the handoff demonstration.

### Human-approved automated click — rejected

**Pros:** Requires approval while keeping execution automated.

**Cons:** Does not prove that a person can take control of and operate the same live session, which the assignment explicitly requests.

## Decision 11: Use a Typed, Versioned JSON Artifact

**Decision:** Use Pydantic-validated JSON with schema version `1.0`, typed inputs/outputs, ordered steps, semantic locators, checkpoints, risk, and business outcomes.

**Pros**

- Human reviewers and calling agents can understand the contract.
- JSON is portable, diffable, serializable, and easy to check into Git.
- Pydantic rejects malformed inputs, unknown fields, and unsupported schema versions.
- Runtime values can be represented as input references instead of stored secrets.

**Cons**

- The schema must evolve carefully as new surfaces and action types are added.
- Strict validation can reject older artifacts without an explicit migration.
- Semantic locators still depend on external UI wording and accessibility quality.

### Artifact rules

- Store one primary locator and at most one fallback.
- Never store screen coordinates or session-local element references.
- Never store raw Claude transcripts, credentials, tokens, or full sensitive inputs.
- Never store executable JavaScript or Python.
- Reject unknown schema versions before replay.

## Decision 12: Use a Single-Process CLI

**Decision:** Keep discovery, replay, browser ownership, evidence, policy, and terminal handoff in one Python process with focused modules.

**Pros**

- Simplifies same-session browser ownership.
- Is easy for reviewers to install, run, and debug.
- Avoids network coordination and distributed state.
- Fits the 3–4 day time box.

**Cons**

- It does not support distributed workers or simultaneous runs at scale.
- A process crash ends the live browser session.
- It is not a production multi-tenant deployment architecture.

### Services, queues, and database — rejected for this submission

**Pros:** Better long-term concurrency, persistence, remote operation, and scale.

**Cons:** Premature infrastructure that does not improve the required vertical slice; explicitly not rewarded by the assignment.

## Decision 13: Use Explicit Safety and Error Contracts

**Decision:** Enforce an exact-host policy and distinguish success, business outcomes, recoverable conditions, and hard failures.

### Safety policy

- Allow only HTTPS on `automationexercise.com` and `www.automationexercise.com`.
- Check the current and destination URL before and after navigation.
- Allow only bounded browser action types.
- Treat page content as untrusted data, never as new instructions.
- Keep sensitive inputs local and redact them recursively from evidence.
- Forbid shell commands, arbitrary JavaScript, downloads, payment, and order submission.

**Pros**

- Prevents the model or an artifact from expanding its authority.
- Produces clear, auditable denials.
- Addresses prompt injection and accidental navigation risks.

**Cons**

- Strict rules can stop legitimate flows after an unexpected redirect.
- New target sites and actions require explicit configuration changes.

### Error taxonomy

- `success`: the final checkpoint passes and typed outputs are returned.
- `business_outcome`: expected result such as `product_not_found`, `authentication_failed`, or `email_already_registered`.
- `recoverable`: known modal dismissal or one retry for a transient load.
- `hard_failure`: invalid artifact, policy denial, ambiguous/missing locator, unexpected dialog, or failed checkpoint. Per Decision 19, an interactive run offers a live-session handoff here before returning.

Business outcomes are evaluated after each action and before the step checkpoint. `session_expired` joins the outcome list.

**Pros**

- Callers can distinguish a legitimate result from a software failure.
- Failures include step, expected state, observed state, and evidence paths.
- Recovery remains bounded and predictable.

**Cons**

- Known outcomes and recoveries must be modeled explicitly.
- A new public-site behavior initially appears as a hard failure.

## Decision 14: Evidence and Testing Strategy

**Decision:** Provide offline tests plus genuine public-site discovery and replay evidence.

### Offline tests

Use pytest with a fake surface and scripted Claude responses for schema validation, policy, redaction, recording, replay outcomes, retry limits, failures, and handoff state transitions.

**Pros**

- Tests run without an API key or network.
- Failure cases are repeatable.
- Core logic can be verified even if the public site is unavailable.

**Cons**

- Fake-surface tests cannot prove that current public-site locators work.

### Live evidence

Check in three artifacts from genuine Claude discoveries, discovery/replay JSONL logs, an unknown-product outcome, and deletion handoff screenshots and records.

**Pros**

- Proves the LLM actually operated a real UI.
- Proves saved artifacts replay without Claude.
- Gives reviewers enough information to debug failures.

**Cons**

- Live runs cost API usage and require network access.
- Evidence may become historical if the public target changes.

## Decision 15: Target a 3–4 Day Delivery

**Decision:** Balance speed and polish over three to four focused days.

### 3–4 day scope

**Pros**

- Enough time for the full vertical slice, tests, evidence, and clear documentation.
- Leaves time for clean-environment reproducibility checks.
- Encourages depth in the schema, replay, errors, safety, and handoff.

**Cons**

- Does not leave room for optional stretch goals or production infrastructure.
- Public-site surprises may consume part of the polish day.

### Planned allocation

- Day 1: typed contracts, policy/redaction, and Playwright surface.
- Day 2: Claude discovery and artifact recording.
- Day 3: replay, error handling, terminal handoff, and evidence.
- Day 4: clean setup test, README, REPORT, evidence curation, and final review.

## Decision 16: Deliberate Cuts

**Decision:** Do not build payment/order submission, a dashboard, true co-browsing, desktop automation, tenant infrastructure, queues, services, databases, replay-time LLM recovery, automatic approval workflows, or stretch goals.

**Amended by Decision 20:** the capability catalog is taken, and minimal tenant overrides (a JSON profile plus locator substitution) move from design-only to built. Same-artifact cross-variant reuse and tenant *infrastructure* — a registry, an override service, storage — stay cut, as does everything else listed here.

**Pros**

- Keeps effort focused on the assignment's highest-weight criteria.
- Reduces security risk and setup complexity.
- Makes a complete, explainable submission achievable.

**Cons**

- Some production-scale concerns remain design-only.
- The operator must be local.
- The implementation demonstrates one concrete web surface only.

## Decision 17: Perceive Through the Accessibility Tree, Not the DOM

**Decision:** `observe()` returns URL, title, and a bounded accessibility snapshot. Claude never receives the DOM or screenshots. Screenshot capture is a separate evidence-only operation. `LocatorSpec` kinds are ranked: `role_name` and `label` primary, `placeholder` and `text` secondary, `css` a last resort that must carry a recorded rationale and is forbidden on the legacy surface.

**Why this changed:** An audit of the plan against the assignment found a direct collision. The brief states, of the agent loop, "bias toward an approach that would still work when the surface has no clean DOM — that's the common case in our environment," and names generalization to that environment as an explicit evaluation criterion. The original design listed the accessibility tree as one input among several and treated `role_name` through `css` as a flat menu of equals. That reads as DOM automation with accessibility as a courtesy.

### Accessibility-first — selected

**Pros**

- It is a structural guarantee, not a convention. Because Claude only ever sees accessible roles, names, and values, it cannot invent a selector from markup it was never shown, so recorded locators are accessibility-shaped by construction.
- The accessibility tree is the representation that survives the target environment: present on legacy server-rendered pages with no test IDs, and exposed by operating systems for native desktop applications.
- `role_name` and `label` map onto Windows UI Automation and macOS accessibility control patterns without translation, so the desktop adapter described in the heterogeneity section needs no schema change.
- The `css` rationale strings answer the brief's request for reasoning about locator robustness, which the original plan did not capture anywhere.

**Cons**

- Accessibility snapshots are noisier than DOM queries and cost more tokens per observation.
- Real pages carry controls with weak or missing accessible names, so `css` cannot be removed outright.
- It constrains discovery: Claude cannot fall back on markup structure when a control is poorly labelled, and will escalate more often than a DOM-capable loop would.

### Keeping the flat locator menu — rejected

**Pros:** Slightly higher discovery success rate on the clean-DOM public target; no rework.

**Cons:** Leaves the submission with no answer to a criterion the brief names twice, and makes the desktop-extension story in the write-up an assertion the implementation does not support.

This revises Decision 7 rather than reversing it. Custom typed tools backed by Playwright remain the mechanism; what changed is the representation those tools perceive.

## Decision 18: Build a Local Hostile Surface as a Second Target

**Decision:** Add `legacy/` — a static lookup page served on the loopback interface using nested-table layout, no test IDs, non-semantic markup, and an interstitial overlay. Its controls retain accessible names. The checked implementation has no frameset/iframe and no confirmation dialog.

**Why:** Decision 3 chose a public site for the strength of its evidence, and that reasoning stands. The local page adds runnable evidence for table-based layout, missing test IDs, an overlay, and accessibility-shaped locators without displacing the public target. It does not claim to cover the brief's iframe/frameset example.

**Pros**

- It makes Decision 17 falsifiable instead of merely argued: on a surface where markup-derived selectors are useless, an accessibility-first design either works or does not.
- It is a similar lookup flow behind different markup and branding, useful for exercising the tenant-profile substitution mechanism.
- It is fully controlled, so the overlay case can be demonstrated on demand rather than waited for.
- It supplies a bounded local tenant-profile demonstration at no additional subsystem cost.

**Cons**

- It is the one place in the plan that adds build work rather than redistributing it.
- It widens the policy surface: `http://127.0.0.1:<port>` becomes an allowlisted origin and the only plaintext-HTTP entry. Mitigated by binding to the loopback address rather than the name `localhost`, and by marking the origin `dev_only` in `config/policy.json` so it is excluded by configuration rather than a code edit.
- A page the author wrote is open to the same "artificially easy" objection raised against the rejected mock banking app. It is written to be hostile rather than convenient, but the author still controls it, and the write-up should say so.

**One constraint this forces:** the page's interactive controls must carry accessible names, through native `label` elements and `aria-label`. Hostile *structure* — table soup, no test IDs, no semantic containers — is what defeats CSS selectors and is the point of the exercise. An inaccessible page would be a different thing entirely: it would leave discovery with nothing to target, forcing the immediate breach of the rule that `css` is forbidden here. Legacy enterprise apps commonly have labelled inputs inside terrible layout markup, so this is the realistic case as well as the workable one.

### Doing nothing and arguing the point in the report — rejected

**Cons:** The brief is explicit that it cannot assess a description of something it can run. The same logic that makes the discovery run mandatory applies to the generalization claim.

## Decision 19: An Interactive Replay Escalates on Hard Failure

**Decision:** When a `hard_failure` occurs in a run started with `--interactive`, replay raises the same `InterventionRequest` used for `requires_human` steps and offers the operator the live session. Non-interactive runs return the failure result unchanged.

**Why:** The brief lists three triggers for human-in-the-loop escalation: the agent is stuck during discovery, a risky step needs a person, and "a replay hits a condition it can't recover from." The original design covered the first two. The third was unhandled — a replay hard failure simply returned a result, which meant the escalation path was reachable only when the artifact had predicted the need in advance.

**Pros**

- Closes a must-have requirement by reusing `TerminalHandoff` unchanged; no new component.
- The interesting case is the unanticipated one. Escalating only on pre-declared steps handles exactly the situations that were already understood.
- Preserves the live session at the moment of failure, when the browser state is still diagnostic.

**Cons**

- Introduces a second path out of `hard_failure`, so the state machine and its tests grow.
- A resumed run's result is no longer purely deterministic — it depends on what the operator did. Recorded explicitly in the result and evidence rather than hidden.

**Why non-interactive runs are excluded:** The production path an agent triggers has no operator to route to. Blocking there would convert a debuggable failure into a hang, which is worse than the failure.

This amends the error taxonomy in Decision 13: `hard_failure` now has an interactive branch.

## Decision 20: Take the Capability Catalog and Demonstrate Tenant Overrides

**Original decision:** Build the capability catalog and demonstrate cross-variant reuse by replaying one base artifact with per-variant locator overrides.

**Implementation ruling:** The catalog is delivered. One hand-authored `legacy_product_lookup` artifact also replays successfully on the base and NorthStar variants through origin rebasing, four locator overrides, and two condition overrides. The public checkout artifact has a different entry URL and step topology, so reuse of that artifact on the legacy surfaces is not claimed.

**Why:** Decision 16 cut all stretch goals on the reasoning that breadth is not rewarded, which remains correct. These two are exceptions because neither adds a subsystem — both are projections of work the core already requires.

- The catalog re-renders the contract the artifact already carries; the modeling exists, only the projection is new. Invocation runs the ordinary replay path and grants no execution authority of its own. It is included because the brief's whole framing is that an artifact is a capability an agent calls, and showing one invoked by name is stronger evidence than describing it.
- Tenant overrides are a small projection over the replay contract and can be demonstrated locally without a registry or service. Full cross-variant reuse requires an explicit entry-URL/step-mapping design and new evidence; locator substitution alone does not prove it.

**Cons**

- Two more things to build on a schedule already carrying a new surface.
- The brief cautions against building scaling infrastructure. Guarded by keeping tenant support to a JSON file and a substitution step — no registry, no override service, no storage layer.

The remaining optional goals — a tenant registry, artifact confidence scoring and approval gating, code generation from artifacts, bounded LLM recovery on replay failure, and multi-run stability reporting — stay cut.

## Amendments From the Assignment Audit

Reading the assignment end to end against the plan produced four decisions above and these corrections to the design of record. Each is recorded here because it changed a stated position, not merely a detail.

- **Business-outcome detection was undefined.** The artifact declared outcome conditions but nothing said when replay evaluated them. They are now evaluated after each action and *before* the step checkpoint. The ordering matters: a not-found page always fails the checkpoint that expected a result page, so checking the checkpoint first would report every legitimate business answer as a failure — the exact conflation the brief's glossary calls the most common design mistake here.
- **Two runtime conditions the brief names were unmodeled.** Session expiry is now an artifact-level business outcome applying at every step of an authenticated flow. `email_already_registered` is labelled as the validation-error case, since the site surfaces it as an inline form error.
- **The artifact was versioned but not provenanced.** `schema_version` versions the format only. Added `artifact_version`, `created_at`, `discovery_run_id`, and `model_id`, so a reviewer can trace any artifact to the run and model that produced it. This is what the brief means by "reviewable."
- **Policy allowlisted hosts but not routes.** A route denylist now rejects payment and order-submission paths before risk classification is consulted, which is what makes "payment is forbidden rather than approvable" an enforced property rather than a described intention.
- **`email` was sensitive in one capability and not another.** Now sensitive in all three. Inconsistent marking would redact the same value in one evidence log and print it in the next.
- **Screenshot redaction had no named mechanism and an unstated limit.** Sensitive fields are masked with Playwright's `mask` argument, so values are painted over before encoding. The residual limit is stated plainly: screenshots of a filled form show the synthetic identity data typed into it, and images are not treated as a redaction boundary.
- **The discovery turn cap was too low.** Raised from 30 to 60. The target's account-creation form has roughly fifteen fields and would consume most of the smaller budget on `fill` calls alone.
- **The human's actions were captured only as a self-reported sentence.** Automation now passively records the operator's navigation trail while control is `HUMAN`, corroborating the summary. It remains a summary rather than a full event stream, which stays a documented limit of the terminal handoff.
- **Submission steps were absent from both documents.** Public repository, URL on its own line, emailed to `assignments@interface.ai` from the application address, no attachment. The email is drafted for review and sent only on explicit approval; commits remain manual.
- **Three discovery runs were committed to without a floor.** The requirement is one genuine run. Three remain planned, with `prepare_product_checkout` as the flagship that must be genuine; any hand-authored artifact is labelled as such in both its provenance and the report. Presenting a hand-authored artifact as a discovered one is not an available fallback.

## Planning Questions and Recorded Answers

The following preserves the questions asked during planning and the answers that changed or confirmed project direction.

1. **Question:** Which LLM API can you use for the genuine discovery run—OpenAI, Anthropic, another provider, or none yet?  
   **Answer:** Anthropic or OpenAI.

2. **Question:** Which language are you more comfortable building this in—Python or TypeScript/Node.js?  
   **Answer:** Python.

3. **Question:** Should we build a local mock legacy-banking web app or automate an existing public demo site?  
   **Answer:** Public demo site, because it provides stronger evidence that the system works.

4. **Question from the developer:** Is there a specific environment required by the PDF?  
   **Recorded answer:** No. Language, runtime, framework, model, computer-use technology, target application, artifact format, and architecture are left to the candidate. A genuine LLM-driven live UI run is mandatory.

5. **Question:** Should we use Automation Exercise or OrangeHRM?  
   **Answer:** Automation Exercise.

6. **Question:** Should the main capability stop at cart review or reach checkout review?  
   **Answer/clarification:** More options were requested, along with confirmation that the project did not have to use a banking target.

7. **Question from the developer:** Are there more workflow options, and should the target be banking-related?  
   **Recorded answer:** Available options included product lookup, cart review, checkout, account management, contact form, product review, and cross-session cart. A banking target is not required; the assignment explicitly permits an e-commerce proxy.

8. **Question:** Should the contact-form capability be optional rather than required?  
   **Initial answer:** The first four numbered options were selected instead, correcting an earlier reference to options 1, 2, 3, and 5.

9. **Question:** For account management, should deletion be included as a human-approved cleanup step, or should the scope stop at register/login/logout?  
   **Answer:** Include deletion.

10. **Question:** Which model provider should the first implementation use: OpenAI or Anthropic?  
    **Initial answer:** OpenAI.

11. **Question from the developer:** Can Claude also be checked?  
    **Recorded answer:** Claude was compared with OpenAI. Claude's browser/tool-use path was judged a cleaner fit for this browser-only discovery task.

12. **Question:** Should discovery switch to Claude or remain on OpenAI?  
    **Answer:** Switch to Claude.

13. **Question:** Should human handoff use a terminal or a small web operator dashboard?  
    **Answer:** Terminal, after reviewing the pros and cons of both.

14. **Question:** Should the system produce one large artifact or three focused capabilities?  
    **Answer:** The three focused artifacts work.

15. **Question:** How much implementation time should the plan target: one focused day, a weekend, or several polished days?  
    **Answer:** A 3–4 day plan balancing speed and polish.

16. **Question:** Which discovery approach should be used: Claude browser-use, custom Claude tools with Playwright, or screenshot/coordinate computer use?  
    **Answer:** Compare them specifically on reproducibility.

17. **Question:** Should custom Claude tools with Playwright be locked in as the reproducibility-first design?  
    **Answer:** Yes—Option B.

18. **Architecture review:** The single-process discovery/replay/policy/evidence/handoff architecture was presented visually.  
    **Answer:** Approved.

19. **Artifact-schema review:** The versioned capability contract, steps, semantic locators, inputs, outputs, checkpoints, risk, and outcomes were presented visually.  
    **Answer:** Approved.

20. **Replay and handoff review:** Deterministic execution, result taxonomy, bounded recovery, failure rules, and the terminal control state machine were presented visually.  
    **Answer:** Approved.

21. **Safety and scale review:** Domain/action policy, redaction, the surface seam, and design-only tenant reuse were presented visually.  
    **Answer:** Approved.

22. **Testing, evidence, and scope review:** Repository layout, minimal stack, offline tests, live evidence, definition of done, and deliberate cuts were presented visually.  
    **Answer:** Approved as workable.

## Change History

- 2026-09-08: Initial design decisions approved.
- 2026-09-08: Provider changed from OpenAI to Claude after comparison.
- 2026-09-08: Reproducibility-first custom Claude tools with Playwright selected.
- 2026-09-09: Consolidated decisions, alternatives, pros/cons, and planning Q&A into this log.
- 2026-09-09: Audited the plan against the assignment PDF. Added Decisions 17–20 (accessibility-first perception, local hostile surface, replay escalation on hard failure, two stretch goals taken), amended Decisions 3, 7, 13, and 16, and recorded ten further corrections under "Amendments From the Assignment Audit".

## Decision 22: Preserve discovery lineage with a raw source copy

**Decision:** A reviewed derivative names its source run in `derived_from`; a raw discovered JSON is copied under `evidence/artifacts/discovered/` and never edited.

**Alternatives:** A flat provenance enum loses the diffable source; editing the discovered artifact destroys the record. Lineage keeps both without adding a history service. No raw copy is claimed until an accepted discovery run exists.

## Decision 23: Record outcomes without evaluating them during discovery

**Decision:** `declare_outcome` records a branch and never evaluates it while discovering.

**Alternatives:** Evaluating a negative branch on the happy path rejects valid discovery; treating it as a failure loses the caller-visible business result. Replay evaluates it after the relevant action.

## Decision 24: Checkpoint navigations automatically

**Decision:** Recorded navigations receive an automatic URL checkpoint; later checkpoints replace only the just-recorded step.

**Alternatives:** The v1 `step_id` retro-attachment could silently attach a claim to the wrong action. Immediate attachment is auditable and makes every recorded navigation checkable.

## Decision 25: Rebase only tenant origins

**Decision:** Tenant rebasing replaces scheme and netloc only; path, query, and fragment remain the reviewed flow.

**Alternatives:** Rewriting paths turns a locator profile into an unreviewed workflow fork. A separate artifact is required when topology changes.

## Decision 26: Recover only from reported interception

**Decision:** Retry a click/fill/select only after `ActionBlocked` proves another element intercepted it; never retry a plain click timeout.

**Alternatives:** Retrying every timeout risks duplicate state-changing actions. A conservative false negative is safer than a double submission.

## Decision 27: Demonstrate two physical legacy variants

**Decision:** Keep base and NorthStar variant pages on separate loopback origins and run one artifact on both.

**Alternatives:** Relabelling one page does not prove tenant reuse. Separate files and ports make rebasing, locator overrides, and version drift observable.

## Decision 28: Prefer accessible names without replacing proven primaries

**Decision:** New locators use accessible names first; a replay-proven test ID remains primary with an accessible fallback.

**Alternatives:** A wholesale locator rewrite creates live drift without evidence. The exception is documented rather than disguised as a new preference.

## Decision 29: Report version drift without blocking replay

**Decision:** Compare `supported_versions` with `product_version` on every tenant run, emit `tenant_version_drift`, and continue.

**Alternatives:** Ignoring drift hides an operational signal; failing on a version string blocks a flow that can still work. Production adds a per-tenant canary and stability signal.

- 2026-09-11: Added audit-remediation decisions 22–29; live evidence claims remain limited to retained run artifacts.
- 2026-09-12: Task 11 live recovery completed: registration and clean checkout review succeeded with the synthetic account; the s23 product-row selector was corrected, with observed `Rs. 500` unit price and product-row total.
