# Threadline — Design Write-Up

## 1. Architecture

This is a Python 3.12 single-process CLI. Discovery gives Claude a fixed typed tool set over `PlaywrightSurface`; policy, Pydantic validation, evidence, and terminal handoff stay in-process. Discovery receives only URL, title, and a bounded accessibility tree. Replay executes saved JSON through the same policy without calling a model. The catalog is a projection of artifact contracts, not another executor.

## 2. Artifact schema

`CapabilityArtifact` is strict Pydantic JSON with revision, source run, model, provenance, typed inputs/outputs, semantic locators, checkpoints, risk, and business outcomes. Runtime values are referenced by input name. Accessible names are primary; the documented exception is the proven test-ID primary on login fields, where an accessible-name fallback is retained rather than changing a live locator without evidence.

`register_test_account.json`, `prepare_product_checkout.json`, and `delete_test_account.json` are reviewed `hand_authored` derivatives whose `derived_from` fields identify their historical discovery runs. `lookup_product_20260911_recovery.json` was genuinely discovered in `discovery-5256f7bddb0f4e0ca06e486363517ab6/`; its byte-identical raw copy is `evidence/artifacts/discovered/lookup_product_20260911_recovery.json`. Its unchanged replay `replay-lookup_product_20260911_recovery-5f4163aa53134c58a76932efaf4de90c/` returned the declared `no_products_found` outcome at `s01`, so it remains raw discovery evidence rather than a reviewed public capability. Boolean outputs mean successful extraction (`false` is unrepresentable); a negative business fact is represented as a business outcome.

## 3. Determinism & error handling

The headline proven public slice is successful registration at `replay-register_test_account-f546e03cb86548798ee88143142fb618/` followed by successful checkout review at `replay-prepare_product_checkout-89dbe2c5c5db4820b82680eb332198be/`, with `product_name`, `unit_price`, and `cart_total` outputs. The synthetic account remains available for this evidence; no payment or order was submitted. Replay checks business outcomes before checkpoints, so retained checkout runs `replay-prepare_product_checkout-630e6064e4b44626b926e0ebb4e42604/` and `replay-prepare_product_checkout-60fe5865bfa74dce9c8d91fb5c6382c6/` return `product_not_found` instead of locator failures. Historical checkout v6 at `replay-prepare_product_checkout-2fa64fda64a74791a987e613564aea84/` reached login but returned `authentication_failed`, while the prior v5 `Added!` checkpoint failure at `replay-prepare_product_checkout-039439f2776f4d9dbb5d79a08d7686b0/` showed the modal; the corrected contract checks the visible `View Cart` link and uniquely selects the product-row total.

`ActionBlocked` means Playwright reported an intercepted interaction and permits one interstitial dismissal; `TimeoutError` is a plain unconfirmed timeout and is not retried for clicks; `LocatorNotFound` means no unique target. The base legacy success `replay-legacy_product_lookup-dba1cdf7330045d7b03a86eb27ba07bd/` records the bounded `interstitial_dismissed` recovery.

## 4. Heterogeneity & multi-tenant

One `legacy_product_lookup` artifact now runs on two variants: base success is `replay-legacy_product_lookup-dba1cdf7330045d7b03a86eb27ba07bd/`, and tenant success is `replay-legacy_product_lookup-45a7775b457a43b0bcce416dd34207e3/`. Tenant replay rebases only scheme and netloc, preserves the recorded path as flow, applies four locator overrides and two per-step condition overrides, and uses the tenant terminal success condition for the renamed result heading. The tenant event log records the rebased URL and `tenant_version_drift`: artifact `supported_versions` 4.2 versus tenant `product_version` 4.3. Drift is reported, never fatal. Production would add a per-tenant replay canary and a stability signal; neither is in this slice.

## 5. Escalation & handoff

Discovery escalation and interactive replay hard failures use the same live-session terminal handoff. Stopped discovery runs now carry a screenshot, including `evidence/discovery-3f1c0ca697e4406c9bf9a980aebc547d/`. Deletion remains human-only; its completed handoff evidence is `replay-delete_test_account-378c6f9f48c34ab08209a99152f8016c/`.

## 6. Safety

Policy exact-matches scheme, host, and port before actions and checks navigation destinations and resulting URLs. `dev_only` origins are denied unless `--allow-dev-origins` is supplied; `replay-legacy_product_lookup-efc19c6cc96c491f9622a88e9201a7e1/` proves the default denial. Payment/order routes are forbidden. Newly written Task 11 evidence contains no developer-absolute paths; older retained evidence was not regenerated. Runtime values are redacted and sensitive fills masked, but screenshots are not a redaction boundary.

`_deletes_account` keyword matching is only a backstop. Risk belongs on each artifact step and is reviewed by a human; expanding a risky-verb list would not make keyword matching the risk model.

## 7. Cuts

Still cut: payment/order submission, remote co-browsing, desktop automation, tenant registry/storage, queues, databases, replay-time LLM recovery, confidence scoring, code generation, and production canaries/stability scoring. Also deliberately not added: a configurable risky-verb list and boolean outputs that can carry `false`.

The failed Task 11 discovery directories remain as iteration evidence; the accepted raw run records both a business outcome and a click checkpoint. The requested quantity was 1; the clean successful evidence observed `unit_price` `Rs. 500` and product-row `cart_total` `Rs. 500`.

## 8. Process retrospective, plan lineage, and tooling

### Retrospective

The main process mistake was not independently re-verifying the first agent's work and plan with a fresh agent from a different LLM provider before implementation continued. The later independent review found omissions that required new tasks and further changes. That avoidable rework caused a two-day delay: the planned Friday submission moved to Monday and required work over the weekend. A second mistake was committing and pushing the project as one large change instead of using smaller, task-scoped commits. That made the work harder to review, trace, and remediate. The lesson is to perform fresh-context, cross-provider verification before accepting an agent's plan and to preserve incremental review points throughout implementation.

### Why there are three plans

1. `docs/superpowers/plans/2026-09-09-computer-use-automation-implementation.md` is the original implementation plan.
2. `docs/superpowers/plans/2026-09-11-assignment-audit-remediation.v1-superseded.md` is the first remediation plan containing the required audit changes. It was superseded rather than silently edited.
3. `docs/superpowers/plans/2026-09-11-assignment-audit-remediation.md` is the authoritative remediation plan produced after the full plan was independently re-verified with Anthropic Claude Fable 5.1.

`decisions.md` records the project owner's decisions concerning the agent: scope, workflows, safety boundaries, human handoff, target systems, model/provider selection, and accepted implementation tradeoffs. It is the decision record rather than an automatically generated rationale.

### Models and providers

- **Anthropic — Claude Opus 5:** the discovery model recorded by the capability artifacts. Opus was chosen over Sonnet for stronger out-of-the-box reliability on long, multi-step browser discovery and tool use, especially the registration workflow. Its higher cost and latency were acceptable because model calls occur only during one-time discovery; deterministic replay makes no LLM calls. With more schedule for agent tuning and validation, Sonnet would be preferred for this bounded workflow.
- **Anthropic — Claude Fable 5.1:** the fresh, independent model used to re-verify the remediation plan before the authoritative third plan was accepted.
- **OpenAI Codex — GPT-5.6 Luna, Terra, and Sol:** Luna handled mechanical implementation and scoped checks, Terra handled integration and review, and Sol was reserved for higher-risk safety and recovery work. During development, model usage and dispatch outcomes were tracked in an internal, git-ignored SDD ledger.

### Plugins, skills, and tools

- **Superpowers:** brainstorming, plan execution, worktree assessment, subagent-driven development, test-driven development, systematic debugging, code-review reception and request, verification-before-completion, and branch-finishing workflows.
- **Ponytail:** minimal-solution and YAGNI review discipline, including reuse of existing code and dependencies before adding abstractions.
- **Development and orchestration:** Codex multi-agent dispatch, the SDD progress ledger, Git staging and diff checks, shell commands, `rg`, `jq`, patch-based editing, and screenshot inspection.
- **Runtime and testing:** Python, the Anthropic SDK, Pydantic, Playwright, headed and headless Chromium, pytest, the standard-library `argparse` CLI and `http.server`, the capability catalog, and the discovery/replay evidence tooling.
