# Threadline

Discover once. Replay with evidence.

Python CLI for discovering a bounded browser workflow with Claude, recording a typed capability artifact, and replaying that artifact deterministically with Playwright. The public target is Automation Exercise; `legacy/` is a local hostile lookup surface used to demonstrate the tenant seam.

## Setup

Run these commands from the repository root. Python 3.12 or later is required.

```sh
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev]"
playwright install chromium
```

Discovery needs an Anthropic key and a synthetic Automation Exercise account. Copy the template, replace only its placeholders, and keep the file untracked:

```sh
cp .env.example .env
```

`.env` uses literal, unquoted `KEY=value` lines:

```text
ANTHROPIC_API_KEY=your-anthropic-api-key
AE_EMAIL=synthetic-account@example.com
AE_PASSWORD=synthetic-account-password
```

Load only those three names without evaluating `.env` as shell code:

```sh
while IFS='=' read -r key value; do
  case "$key" in
    ANTHROPIC_API_KEY|AE_EMAIL|AE_PASSWORD) export "$key=$value" ;;
  esac
done < .env
```

## Verify offline

```sh
pytest
python -m automation.cli capabilities list
```

Both commands need no API key. The catalog reads the checked-in artifacts and prints their callable schemas.

## Discover, then replay

With the environment above loaded and a synthetic account, create a fresh capability name so the CLI does not overwrite an existing artifact:

```sh
capability="checkout_$(date +%Y%m%d%H%M%S)"
python -m automation.cli discover \
  --goal "Search for Blue Top, add it to the cart, and stop at checkout review before payment." \
  --capability "$capability" \
  --description "Synthetic-account checkout review; never submit payment or an order." \
  --inputs config/inputs.example.json \
  --vendor-product automationexercise
python -m automation.cli replay \
  --artifact "evidence/artifacts/$capability.json" \
  --inputs config/inputs.example.json
```

Discovery is the only command here that calls Anthropic. Replay executes the saved JSON artifact and makes no model call. Payment and order routes are denied by `config/policy.json`.

## Replay checked-in evidence without an API key

This serves both local legacy variants, replays the base artifact unchanged, then applies the tenant profile, the declared not-found branch, and always stops both servers when the subshell exits:

```sh
(
  python -m http.server 8000 --bind 127.0.0.1 --directory legacy/base &
  base_pid=$!
  python -m http.server 8001 --bind 127.0.0.1 --directory legacy/variant_b &
  variant_pid=$!
  trap 'kill "$base_pid" "$variant_pid" 2>/dev/null; wait "$base_pid" "$variant_pid" 2>/dev/null' EXIT INT TERM
  python -m automation.cli replay \
    --allow-dev-origins \
    --artifact evidence/artifacts/legacy_product_lookup.json \
    --inputs config/legacy_product_lookup.inputs.json
  python -m automation.cli replay \
    --allow-dev-origins \
    --artifact evidence/artifacts/legacy_product_lookup.json \
    --inputs config/legacy_product_lookup.inputs.json \
    --tenant config/tenants/legacy_variant.json
  python -m automation.cli replay \
    --allow-dev-origins \
    --artifact evidence/artifacts/legacy_product_lookup.json \
    --inputs config/legacy_product_lookup.notfound.inputs.json
)
```

This path requires Chromium but neither `ANTHROPIC_API_KEY` nor public-site credentials. It is a local, hand-authored lookup-only artifact; see `REPORT.md` for its scope and the checked-in successful evidence.

## Evidence

Run evidence is written under `evidence/replay-<capability>-<uuid>/` or `evidence/discovery-<uuid>/`. Notable checked-in results include:

- fresh successful synthetic registration (account remains available for checkout evidence): `evidence/replay-register_test_account-f546e03cb86548798ee88143142fb618/`;
- successful checkout review with `Blue Top`: `evidence/replay-prepare_product_checkout-89dbe2c5c5db4820b82680eb332198be/`;
- completed cleanup through a human deletion handoff: `evidence/replay-delete_test_account-378c6f9f48c34ab08209a99152f8016c/`;
- direct and catalog-invoked `product_not_found`: `evidence/replay-prepare_product_checkout-630e6064e4b44626b926e0ebb4e42604/` and `evidence/replay-prepare_product_checkout-60fe5865bfa74dce9c8d91fb5c6382c6/`;
- genuine lookup discovery, byte-identical raw copy, and unchanged replay: `evidence/discovery-5256f7bddb0f4e0ca06e486363517ab6/`, `evidence/artifacts/discovered/lookup_product_20260911_recovery.json`, and `evidence/replay-lookup_product_20260911_recovery-5f4163aa53134c58a76932efaf4de90c/`;
- base legacy lookup with intercepted-click recovery: `evidence/replay-legacy_product_lookup-dba1cdf7330045d7b03a86eb27ba07bd/`;
- tenant legacy lookup with rebasing and version drift: `evidence/replay-legacy_product_lookup-45a7775b457a43b0bcce416dd34207e3/`;
- legacy not-found business outcome and default dev-origin denial: `evidence/replay-legacy_product_lookup-8c44da524fef49c8be4aaa78e7668f17/` and `evidence/replay-legacy_product_lookup-efc19c6cc96c491f9622a88e9201a7e1/`.

Structured artifacts, events, and results are redacted at the evidence boundary; screenshots receive targeted masks only and are not a general redaction boundary. Use synthetic data.
