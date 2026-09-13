"""Command-line entry points. Wiring only — no logic lives here."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from automation.catalog import CapabilityCatalog
from automation.evidence import EvidenceWriter
from automation.handoff import TerminalHandoff
from automation.models import CapabilityArtifact, TenantProfile
from automation.policy import PolicyEngine, load_policy
from automation.replay import ReplayRunner
from automation.surface import PlaywrightSurface

DEFAULT_POLICY = "config/policy.json"
EVIDENCE_ROOT = "evidence"


class CliError(Exception):
    def __init__(self, source: str, category: str):
        self.source, self.category = source, category

    def __str__(self) -> str:
        return f"{self.source}: {self.category}"


class _MissingEnvironment(Exception):
    def __init__(self, key: str, name: str):
        self.key, self.name = key, name


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="automation")
    subs = parser.add_subparsers(dest="command", required=True)

    discover = subs.add_parser("discover", help="Run Claude against a live surface.")
    discover.add_argument("--goal", required=True)
    discover.add_argument("--capability", required=True)
    discover.add_argument("--description", default="")
    discover.add_argument("--inputs", required=True)
    discover.add_argument("--spec", help="JSON file declaring input types and sensitivity.")
    discover.add_argument("--model", default="claude-opus-5")
    discover.add_argument("--out", default="evidence/artifacts")
    discover.add_argument("--policy", default=DEFAULT_POLICY)
    discover.add_argument("--vendor-product", default="automationexercise",
                          help="Vendor product name recorded in the artifact's target.")

    replay = subs.add_parser("replay", help="Execute a saved artifact. No model.")
    replay.add_argument("--artifact", required=True)
    replay.add_argument("--inputs", required=True)
    replay.add_argument("--tenant")
    replay.add_argument("--interactive", action="store_true",
                        help="Offer a live-session handoff on a hard failure.")
    replay.add_argument("--headless", action="store_true")
    replay.add_argument("--policy", default=DEFAULT_POLICY)

    capabilities = subs.add_parser("capabilities", help="List or invoke saved capabilities.")
    cap_subs = capabilities.add_subparsers(dest="subcommand", required=True)
    cap_subs.add_parser("list").add_argument("--dir", default="evidence/artifacts")
    invoke = cap_subs.add_parser("invoke")
    invoke.add_argument("name")
    invoke.add_argument("--dir", default="evidence/artifacts")
    invoke.add_argument("--args", required=True, help="JSON object of typed arguments.")
    invoke.add_argument("--policy", default=DEFAULT_POLICY)
    invoke.add_argument("--headless", action="store_true")
    for parser_needing_dev in (discover, replay, invoke):
        parser_needing_dev.add_argument(
            "--allow-dev-origins", action="store_true",
            help="Permit origins marked dev_only in the policy file (local surfaces).")
    return parser


def _read_json(path: str, source: str):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise CliError(source, "invalid JSON") from None


def _parse_json(value: str, source: str):
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        raise CliError(source, "invalid JSON") from None


def _resolve_inputs(data: object) -> tuple[dict, set[str]]:
    if not isinstance(data, dict):
        raise CliError("inputs", "must be a JSON object")
    out = {}
    for key, value in data.items():
        if not isinstance(key, str):
            raise CliError("inputs", "keys must be strings")
        if isinstance(value, dict):
            if set(value) != {"env"} or not isinstance(value["env"], str) or not value["env"]:
                raise CliError("inputs", "invalid environment descriptor")
            resolved = os.environ.get(value["env"])
            if resolved is None:
                raise _MissingEnvironment(key, value["env"])
            out[key] = resolved
            continue
        if isinstance(value, bool) or isinstance(value, (str, int)):
            out[key] = value
            continue
        raise CliError("inputs", "values must be strings, integers, booleans, or environment descriptors")
    return out, {key for key, value in data.items() if isinstance(value, dict)}


def _load_inputs(path: str) -> tuple[dict, set[str]]:
    return _resolve_inputs(_read_json(path, "inputs"))


def load_inputs(path: str) -> dict:
    """Load runtime inputs, resolving ``{"env": "NAME"}`` values from the environment."""
    try:
        return _load_inputs(path)[0]
    except _MissingEnvironment as exc:
        sys.exit(f"error: {exc.key!r} needs environment variable {exc.name!r}, which is not set")


def _parse_model(model, data: object, source: str):
    if not isinstance(data, dict):
        raise CliError(source, "must be a JSON object")
    try:
        return model(**data)
    except (TypeError, ValidationError):
        raise CliError(source, "invalid fields") from None


def _inside(root: str | Path, name: str, suffix: str = "") -> Path:
    root_path = Path(root).resolve()
    child = (root_path / f"{name}{suffix}").resolve()
    try:
        child.relative_to(root_path)
    except ValueError:
        raise CliError("output", "unsafe path") from None
    return child


def _with_env_sensitive(artifact: CapabilityArtifact, names: set[str]) -> CapabilityArtifact:
    if not names:
        return artifact
    inputs = {
        name: spec.model_copy(update={"sensitive": spec.sensitive or name in names})
        for name, spec in artifact.inputs.items()
    }
    return artifact.model_copy(update={"inputs": inputs})


def _policy(path: str, allow_dev: bool) -> PolicyEngine:
    try:
        return PolicyEngine(load_policy(path), allow_dev_origins=allow_dev)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValidationError):
        raise CliError("policy", "invalid file or fields") from None


def main(argv=None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.command == "replay":
            return _replay(args)
        if args.command == "capabilities":
            return _capabilities(args)
        return _discover(args)
    except _MissingEnvironment:
        print("error: inputs: required environment variable is not set", file=sys.stderr)
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValidationError, ValueError, KeyError):
        print("error: command: invalid input", file=sys.stderr)
    return 2


def _replay(args, artifact=None, inputs=None, env_sensitive_names=None) -> int:
    artifact = artifact or _parse_model(CapabilityArtifact, _read_json(args.artifact, "artifact"), "artifact")
    if inputs is None:
        inputs, env_sensitive_names = _load_inputs(args.inputs)
    artifact = _with_env_sensitive(artifact, env_sensitive_names or set())
    tenant = (_parse_model(TenantProfile, _read_json(args.tenant, "tenant"), "tenant")
              if getattr(args, "tenant", None) else None)
    run_dir = _inside(EVIDENCE_ROOT, f"replay-{artifact.name}-{uuid4().hex}")
    evidence = EvidenceWriter(run_dir.parent, run_dir.name, artifact.sensitive_input_names())
    with PlaywrightSurface(headless=args.headless) as surface:
        result = ReplayRunner(
            artifact=artifact, policy=_policy(args.policy, getattr(args, "allow_dev_origins", False)), evidence=evidence,
            surface=surface, tenant=tenant, handoff=TerminalHandoff(evidence),
            interactive=getattr(args, "interactive", False),
        ).run(inputs)
    print(json.dumps(result.model_dump(), indent=2))
    return 0 if result.status in ("success", "business_outcome") else 1


def _capabilities(args) -> int:
    catalog = CapabilityCatalog(args.dir)
    try:
        if args.subcommand == "list":
            for entry in catalog.list():
                print(json.dumps({**catalog.tool_schema(entry["name"]),
                                  **{key: entry[key] for key in
                                     ("artifact_version", "provenance", "derived_from")}}, indent=2))
            return 0
        artifact = catalog.get(args.name)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValidationError, ValueError, KeyError):
        raise CliError("capability artifact", "invalid file or fields") from None
    inputs, names = _resolve_inputs(_parse_json(args.args, "arguments"))
    args.tenant = None
    args.interactive = False
    return _replay(args, artifact=artifact, inputs=inputs, env_sensitive_names=names)


def _discover(args) -> int:
    from anthropic import Anthropic

    from automation.discovery import DiscoveryRunner
    from automation.models import InputSpec

    inputs, env_sensitive_names = _load_inputs(args.inputs)
    spec_source = _read_json(args.spec, "spec") if args.spec else {}
    if not isinstance(spec_source, dict) or not all(isinstance(name, str) and isinstance(spec, dict)
                                                    for name, spec in spec_source.items()):
        raise CliError("spec", "must map names to input specifications")
    specs = {}
    for name, value in inputs.items():
        default = {
            "type": "boolean" if isinstance(value, bool) else "integer" if isinstance(value, int) else "string",
            "sensitive": name in ("password", "email") or name in env_sensitive_names,
        }
        spec = _parse_model(InputSpec, spec_source.get(name, default), "spec")
        specs[name] = spec.model_copy(update={"sensitive": spec.sensitive or name in env_sensitive_names})
    run_id = f"discovery-{uuid4().hex}"
    run_dir = _inside(EVIDENCE_ROOT, run_id)
    evidence = EvidenceWriter(run_dir.parent, run_dir.name, {name for name, spec in specs.items() if spec.sensitive})
    with PlaywrightSurface(headless=False) as surface:
        runner = DiscoveryRunner(
            client=Anthropic(), surface=surface, policy=_policy(args.policy, getattr(args, "allow_dev_origins", False)),
            evidence=evidence, goal=args.goal, capability_name=args.capability,
            description=args.description or args.goal, inputs=specs, model_id=args.model,
            run_id=run_id, handoff=TerminalHandoff(evidence),
            vendor_product=args.vendor_product,
        )
        runner.set_runtime_values(inputs)
        artifact = runner.run()

    if artifact is None:
        print(f"Discovery did not produce an artifact. See {evidence.run_dir}/events.jsonl")
        return 1
    out = _inside(args.out, artifact.name, ".json")
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        with out.open("x", encoding="utf-8") as handle:
            handle.write(artifact.model_dump_json(indent=2))
    except FileExistsError:
        raise CliError("output", "artifact already exists")
    print(f"Saved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
