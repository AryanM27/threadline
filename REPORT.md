# Threadline — Design Write-Up

## 1. Architecture

- **Runtime:** Python 3.12, single-process CLI. Policy, Pydantic validation, evidence capture, and terminal handoff remain in-process.
- **Discovery:** Claude receives a fixed typed tool set over `PlaywrightSurface` and sees only the URL, title, and a bounded accessibility tree.
- **Replay:** Saved JSON executes through the same policy without calling a model.
- **Catalog:** Capability contracts are projected directly from artifacts rather than implemented by a second executor.

## 2. Artifact schema

- **Contract:** `CapabilityArtifact` is strict Pydantic JSON carrying revision, source run, model, provenance, typed inputs and outputs, semantic locators, checkpoints, risk, and business outcomes.
- **Runtime values:** Steps reference input names; credentials and other runtime values are not embedded in artifacts.
- **Locator policy:** Accessible names are primary. The documented exception is the proven test-ID primary on login fields, where an accessible-name fallback is retained rather than replacing a live-tested locator.
- **Reviewed derivatives:** `register_test_account.json`, `prepare_product_checkout.json`, and `delete_test_account.json` are `hand_authored`; each `derived_from` value identifies its historical discovery run.
- **Genuine discovery:** `lookup_product_20260911_recovery.json` came from `discovery-5256f7bddb0f4e0ca06e486363517ab6/`. Its raw copy at `evidence/artifacts/discovered/lookup_product_20260911_recovery.json` is byte-identical, and unchanged replay `replay-lookup_product_20260911_recovery-5f4163aa53134c58a76932efaf4de90c/` returned `no_products_found` at `s01`. It remains raw evidence rather than a reviewed public capability.
- **Outcome convention:** Boolean outputs represent successful extraction, so `false` is unrepresentable; negative business facts use business outcomes.

## 3. Determinism & error handling

- **Proven public path:** Registration succeeded in `replay-register_test_account-f546e03cb86548798ee88143142fb618/`; checkout review then succeeded in `replay-prepare_product_checkout-89dbe2c5c5db4820b82680eb332198be/` with `product_name`, `unit_price`, and `cart_total`. The synthetic account remains available; no payment or order was submitted.
- **Business outcomes:** Replay checks them before checkpoints. Direct and catalog-invoked runs `replay-prepare_product_checkout-630e6064e4b44626b926e0ebb4e42604/` and `replay-prepare_product_checkout-60fe5865bfa74dce9c8d91fb5c6382c6/` return `product_not_found` instead of locator failures.
- **Historical correction:** Checkout v6 at `replay-prepare_product_checkout-2fa64fda64a74791a987e613564aea84/` reached login but returned `authentication_failed`. The earlier v5 run `replay-prepare_product_checkout-039439f2776f4d9dbb5d79a08d7686b0/` showed the modal despite failing its `Added!` checkpoint; the corrected contract checks the visible `View Cart` link and uniquely selects the product-row total.
- **Failure classes:** `ActionBlocked` means Playwright reported an intercepted interaction; `TimeoutError` is an unconfirmed timeout and does not permit a click retry; `LocatorNotFound` means no unique target.
- **Bounded recovery:** Only `ActionBlocked` permits one interstitial dismissal. Base legacy run `replay-legacy_product_lookup-dba1cdf7330045d7b03a86eb27ba07bd/` records `interstitial_dismissed`.

## 4. Heterogeneity & multi-tenant

- **Reuse:** One `legacy_product_lookup` artifact runs on the base variant (`replay-legacy_product_lookup-dba1cdf7330045d7b03a86eb27ba07bd/`) and tenant variant (`replay-legacy_product_lookup-45a7775b457a43b0bcce416dd34207e3/`).
- **Rebasing:** Tenant replay replaces only scheme and netloc while preserving the recorded path and flow.
- **Overrides:** The tenant applies four locator overrides, two per-step condition overrides, and its own terminal condition for the renamed result heading.
- **Drift:** Evidence records `tenant_version_drift` from supported version 4.2 to tenant version 4.3. Drift is reported, not fatal.
- **Production extension:** Add per-tenant replay canaries and stability signals; neither is implemented in this slice.

## 5. Escalation & handoff

- **Shared mechanism:** Discovery escalation and interactive replay hard failures use the same live-session terminal handoff.
- **Context:** Stopped discovery runs include a screenshot, including `evidence/discovery-3f1c0ca697e4406c9bf9a980aebc547d/`.
- **Human-only deletion:** Completed handoff evidence is `replay-delete_test_account-378c6f9f48c34ab08209a99152f8016c/`.

## 6. Safety

- **Origin policy:** Scheme, host, and port are exact-matched before actions; navigation destinations and resulting URLs are checked again.
- **Development origins:** `dev_only` origins require `--allow-dev-origins`; `replay-legacy_product_lookup-efc19c6cc96c491f9622a88e9201a7e1/` proves default denial.
- **Forbidden actions:** Payment and order routes are blocked. `_deletes_account` keyword matching is only a backstop; risk declared on each reviewed artifact step is authoritative.
- **Sensitive data:** Runtime values are redacted and sensitive fills are masked. Screenshots are not a general redaction boundary.
- **Path hygiene:** Newly written Task 11 evidence contains no developer-absolute paths; older retained evidence was not regenerated.
- **Deliberate limit:** Expanding a risky-verb list would not turn keyword matching into the risk model.

## 7. Cuts

- **Not implemented:** Payment or order submission, remote co-browsing, desktop automation, tenant registry or storage, queues, databases, replay-time LLM recovery, confidence scoring, code generation, and production canaries or stability scoring.
- **Also excluded:** A configurable risky-verb list and boolean outputs capable of carrying `false`.
- **Retained evidence:** Failed Task 11 discovery directories remain as iteration evidence; the accepted raw run records a business outcome and a click checkpoint.
- **Verified quantity:** Requested quantity was 1; clean successful evidence observed `unit_price` `Rs. 500` and product-row `cart_total` `Rs. 500`.

### Retrospective

- The first agent work and plan were not independently re-verified by a fresh agent from another LLM provider before implementation continued.
- Later independent review found omissions, added tasks, and caused avoidable rework: the planned Friday submission moved to Monday and required weekend work.
- The project was also committed and pushed as one large change rather than smaller task-scoped commits, reducing reviewability and traceability.
- **Lesson:** Perform fresh-context, cross-provider verification before accepting an agent plan and preserve incremental review points throughout implementation.

### Why there are three plans

1. `docs/superpowers/plans/2026-09-09-computer-use-automation-implementation.md` is the original implementation plan.
2. `docs/superpowers/plans/2026-09-11-assignment-audit-remediation.v1-superseded.md` is the first remediation plan containing the required audit changes. It was superseded rather than silently edited.
3. `docs/superpowers/plans/2026-09-11-assignment-audit-remediation.md` is the authoritative remediation plan produced after the full plan was independently re-verified with Anthropic Claude Fable 5.1.

- `decisions.md` records the project owner decisions concerning agent scope, workflows, safety boundaries, human handoff, target systems, model/provider selection, and accepted tradeoffs; it is not an automatically generated rationale.

### Models and providers

- **Anthropic — Claude Opus 5, Fable 5.1, Sonnet 5, and Haiku 4.5:**
  - Opus wrote the original implementation plan and powered capability discovery; Fable independently re-verified the remediation plan; Sonnet handled implementation, review, and final documentation work; Haiku handled mechanical implementation work.
  - Opus was the discovery model recorded by the capability artifacts and was selected over Sonnet for stronger out-of-the-box reliability on long, multi-step browser discovery and tool use, especially registration. Its higher cost and latency were acceptable because model calls occur only during one-time discovery; deterministic replay makes no LLM calls. With more time for agent tuning and validation, Sonnet would be preferred for this bounded workflow.
- **OpenAI Codex — GPT-5.6 Luna, Terra, and Sol:** Luna handled mechanical implementation and scoped checks, Terra handled integration and review, and Sol was reserved for higher-risk safety and recovery work. During development, model usage and dispatch outcomes were tracked in an internal, git-ignored SDD ledger.

### Plugins, skills, and tools

- **Superpowers:** brainstorming, plan execution, worktree assessment, subagent-driven development, test-driven development, systematic debugging, code-review reception and request, verification-before-completion, and branch-finishing workflows.
- **Ponytail:** minimal-solution and YAGNI review discipline, including reuse of existing code and dependencies before adding abstractions.
- **Development and orchestration:** Codex multi-agent dispatch, the SDD progress ledger, Git staging and diff checks, shell commands, `rg`, `jq`, patch-based editing, and screenshot inspection.
- **Runtime and testing:** Python, the Anthropic SDK, Pydantic, Playwright, headed and headless Chromium, pytest, the standard-library `argparse` CLI and `http.server`, the capability catalog, and the discovery/replay evidence tooling.
