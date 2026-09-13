# Task 11 report

## Commands and results

- Legacy servers were served from `legacy/base` on 8000 and `legacy/variant_b` on 8001. The four required replays produced the accepted base success, tenant success/drift, not-found outcome, and default policy denial below.
- Historical phase check: `.venv/bin/pytest -q` reported `198 passed in 0.25s`; this is not the final test count.
- `find evidence -mindepth 1 -maxdepth 1 -type d -empty | wc -l`: `0`.
- `python -m automation.cli capabilities list`: runs without credentials and prints `artifact_version`, `provenance`, and `derived_from`; after recovery it includes the accepted discovered artifact.
- The live discovery command was run three times before the bounded stop and exactly once during recovery, after loading `.env` without printing it. Each run was inspected before proceeding.
- `prepare_product_checkout` was replayed twice. The first proved the v5 modal checkpoint was unstable despite the visible modal; v6 uses the visible `View Cart` control. The v6 run then returned the declared `authentication_failed` business outcome.

## Accepted legacy evidence

- Base success and `interstitial_dismissed`: `evidence/replay-legacy_product_lookup-dba1cdf7330045d7b03a86eb27ba07bd/`.
- Tenant success, origin rebase, four locator overrides, two condition overrides, and `tenant_version_drift`: `evidence/replay-legacy_product_lookup-45a7775b457a43b0bcce416dd34207e3/`.
- Not-found business outcome: `evidence/replay-legacy_product_lookup-8c44da524fef49c8be4aaa78e7668f17/`.
- Default dev-origin denial: `evidence/replay-legacy_product_lookup-efc19c6cc96c491f9622a88e9201a7e1/`.

The initial failed tenant run remains local and unstaged as diagnostic evidence; the terminal condition was base-specific. A test-first `success_condition_override` fixes that contract for the tenant profile.

## Initial live discovery and checkout blockers

1. `discovery-65a309d820884c879cfe9a08252b6622` stopped because `observe` treated initial `about:blank` as an off-policy action. A focused test and one-condition fix exempt observation only; actions remain checked.
2. `discovery-74b08b4347e646ea84a8593768450ddf` reached the public products page but did not associate the supplied `product` runtime input with its search query. A focused test makes runtime input names explicit in the initial prompt.
3. `discovery-3f1c0ca697e4406c9bf9a980aebc547d` escalated without navigating to the supplied public origin. At the initial bounded stop, the three-attempt limit had been reached and no artifact or raw discovered copy existed.
4. `replay-prepare_product_checkout-039439f2776f4d9dbb5d79a08d7686b0` shows the v5 checkpoint failure; `replay-prepare_product_checkout-2fa64fda64a74791a987e613564aea84` reaches login and returns `authentication_failed`. A valid synthetic account is required for a current checkout success.

## Evidence and staging

All Task 11 discovery/replay event logs were checked for runtime secret values without printing those values. Newly written evidence has no `/Users/aryanmamidwar` path. README, REPORT, and decisions cite the clean checkout success and remove obsolete `88f` legacy references.

Staging initially failed under the filesystem sandbox (`.git/index.lock`); elevated Git-index access staged Task 11 docs, code/tests, accepted legacy evidence, retained discovery attempts, and the checkout diagnostics. No commit was created.

## Recovery

- Attempt 3 exposed a concrete prompt defect: `DiscoveryRunner` stored the configured base URL only in the recorder, so the model received no allowed starting URL, guessed `http://localhost:3000/products`, and escalated after policy denial.
- The focused regression test failed before the fix and passed after the runner added its configured base URL to the initial prompt. The discovery suite passed `41` tests; the full suite passed `199` tests before the artifact was added.
- Exactly one additional live discovery attempt was spent. `discovery-5256f7bddb0f4e0ca06e486363517ab6` produced `lookup_product_20260911_recovery.json` with discovered provenance, a business outcome, and a checkpoint on click `s04`.
- `evidence/artifacts/discovered/lookup_product_20260911_recovery.json` is a byte-identical raw copy (SHA-256 `12b588e1b58b42220945efb232df27ff378b24c27e9f2245887d7ac142cdb60d`). The unchanged replay is `replay-lookup_product_20260911_recovery-5f4163aa53134c58a76932efaf4de90c` / `replay-74e68aa9`; it returned the artifact's declared `no_products_found` outcome at `s01`, so the raw artifact was not edited or promoted as a reviewed capability.
- Adding the immutable raw artifact exposed two Task 9 tests that applied human-review conventions to all root artifacts. The ruling keeps validation/checkpoints on every shipped artifact but scopes fallback and condition-comment conventions to `hand_authored` artifacts. Historical phase checks passed `8` focused tests and `200` full-suite tests; the raw hash stayed unchanged.
- Credential-value scans were clean. The retained Task 8 base, tenant, not-found, and policy-denial runs still match README and REPORT. Checkout remains blocked only by the supplied account's `authentication_failed` outcome; no account or credential was changed.

## Fix round 1

- REPORT now limits the absolute-path hygiene claim to newly written Task 11 evidence and states that older retained evidence was not regenerated. README contained no equivalent path-hygiene overclaim and was unchanged.
- Removed the two intentionally excluded untracked retry directories: `replay-delete_test_account-e1be4554c8df4c3a8b9d16e33e83d6c3/` and `replay-legacy_product_lookup-133f754fcac741f0853badf4838e8d46/`. They were not tracked by Git and are not recoverable from the repository.
- Focused wording/path checks passed, both retry directories are absent, and a historical phase check `.venv/bin/pytest -q` passed `200` tests in `0.28s`. No browser, network, or API call was made.
- Final reviewer verification: the current suite passed `203` tests; this is the final test count for Task 11.
