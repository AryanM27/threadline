import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

import automation.cli as cli
from automation.cli import CliError, build_parser, load_inputs, main
from automation.evidence import EvidenceWriter
from automation.models import CapabilityArtifact, InputSpec
from automation.policy import Policy, PolicyEngine, PolicyDenied
from automation.replay import ReplayRunner
from tests.fakes import FakeSurface, checkout_artifact


def test_replay_requires_artifact_and_inputs():
    args = build_parser().parse_args(
        ["replay", "--artifact", "a.json", "--inputs", "i.json"])
    assert args.command == "replay"
    assert args.interactive is False
    assert args.tenant is None


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


def test_replay_accepts_interactive_and_tenant():
    args = build_parser().parse_args(
        ["replay", "--artifact", "a.json", "--inputs", "i.json",
         "--interactive", "--tenant", "config/tenants/legacy_variant.json"])
    assert args.interactive is True
    assert args.tenant.endswith("legacy_variant.json")


def test_discover_requires_goal_and_capability():
    args = build_parser().parse_args(
        ["discover", "--goal", "do a thing", "--capability", "demo",
         "--inputs", "i.json"])
    assert args.goal == "do a thing"


def test_capabilities_list_prints_provenance_and_derivation(tmp_path, capsys):
    artifact = checkout_artifact(provenance="hand_authored", derived_from="discovery-abc")
    (tmp_path / "prepare_product_checkout.json").write_text(artifact.model_dump_json())

    assert main(["capabilities", "list", "--dir", str(tmp_path)]) == 0

    listed = json.loads(capsys.readouterr().out)
    assert listed["provenance"] == "hand_authored"
    assert listed["derived_from"] == "discovery-abc"


def test_inputs_load_from_a_file(tmp_path):
    path = tmp_path / "i.json"
    path.write_text(json.dumps({"product": "Blue Top", "quantity": 2}))
    assert load_inputs(str(path)) == {"product": "Blue Top", "quantity": 2}


def test_inputs_fall_back_to_environment_for_secrets(tmp_path, monkeypatch):
    path = tmp_path / "i.json"
    path.write_text(json.dumps({"product": "Blue Top", "password": {"env": "AE_PASS"}}))
    monkeypatch.setenv("AE_PASS", "hunter2")
    loaded = load_inputs(str(path))
    assert loaded["password"] == "hunter2"


def test_missing_environment_variable_is_a_clear_error(tmp_path):
    path = tmp_path / "i.json"
    path.write_text(json.dumps({"password": {"env": "NOT_SET_ANYWHERE"}}))
    with pytest.raises(SystemExit):
        load_inputs(str(path))


@pytest.mark.parametrize("name", ["", "../escape", "nested/name", ".", "/absolute"])
def test_artifact_name_must_be_a_safe_single_path_component(name):
    data = checkout_artifact().model_dump()
    data["name"] = name
    with pytest.raises(ValueError):
        CapabilityArtifact(**data)


@pytest.mark.parametrize("payload", [
    [],
    {"pin": 1.5},
    {"pin": {"env": ""}},
    {"pin": {"env": "AE_PIN", "extra": True}},
])
def test_inputs_require_an_object_of_scalars_or_exact_env_descriptors(tmp_path, payload):
    path = tmp_path / "inputs.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(CliError):
        load_inputs(str(path))


class _SurfaceContext:
    def __enter__(self):
        return FakeSurface()

    def __exit__(self, *exc):
        return None


class _SuccessfulResult:
    status = "success"

    def model_dump(self):
        return {}


def _capture_replay(monkeypatch):
    captured = []

    class Runner:
        def __init__(self, **kwargs):
            captured.append(kwargs)

        def run(self, inputs):
            captured[-1]["runtime_inputs"] = inputs
            return _SuccessfulResult()

    monkeypatch.setattr(cli, "PlaywrightSurface", lambda **_: _SurfaceContext())
    monkeypatch.setattr(cli, "ReplayRunner", Runner)
    return captured


def test_replay_marks_environment_inputs_sensitive_for_runner(tmp_path, monkeypatch):
    artifact = checkout_artifact()
    artifact.inputs["pin"] = InputSpec(type="string")
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(artifact.model_dump_json())
    inputs_path = tmp_path / "inputs.json"
    inputs_path.write_text(json.dumps({"pin": {"env": "AE_PIN"}}))
    monkeypatch.setenv("AE_PIN", "1234")
    captured = _capture_replay(monkeypatch)

    assert main(["replay", "--artifact", str(artifact_path), "--inputs", str(inputs_path)]) == 0
    assert captured[0]["artifact"].inputs["pin"].sensitive is True
    assert captured[0]["runtime_inputs"] == {"pin": "1234"}


def test_capability_invoke_resolves_and_marks_environment_inputs_sensitive(tmp_path, monkeypatch):
    artifact = checkout_artifact()
    artifact.inputs["pin"] = InputSpec(type="string")
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "prepare_product_checkout.json").write_text(artifact.model_dump_json())
    monkeypatch.setenv("AE_PIN", "1234")
    captured = _capture_replay(monkeypatch)

    assert main([
        "capabilities", "invoke", "prepare_product_checkout", "--dir", str(artifact_dir),
        "--args", json.dumps({"pin": {"env": "AE_PIN"}}),
    ]) == 0
    assert captured[0]["artifact"].inputs["pin"].sensitive is True
    assert captured[0]["runtime_inputs"] == {"pin": "1234"}


def test_discovery_marks_environment_inputs_sensitive_and_infers_booleans(tmp_path, monkeypatch):
    captured = {}
    inputs_path = tmp_path / "inputs.json"
    inputs_path.write_text(json.dumps({"pin": {"env": "AE_PIN"}, "enabled": True}))
    monkeypatch.setenv("AE_PIN", "1234")

    class Runner:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def set_runtime_values(self, values):
            captured["values"] = values

        def run(self):
            return checkout_artifact(name="discover_test")

    anthropic = ModuleType("anthropic")
    anthropic.Anthropic = lambda: object()
    monkeypatch.setitem(sys.modules, "anthropic", anthropic)
    import automation.discovery as discovery
    monkeypatch.setattr(discovery, "DiscoveryRunner", Runner)
    monkeypatch.setattr(cli, "PlaywrightSurface", lambda **_: _SurfaceContext())

    assert main([
        "discover", "--goal", "test", "--capability", "discover_test",
        "--inputs", str(inputs_path), "--out", str(tmp_path / "out"),
        "--vendor-product", "servicing_console",
    ]) == 0
    assert captured["inputs"]["pin"].sensitive is True
    assert captured["inputs"]["enabled"].type == "boolean"
    assert captured["run_id"].startswith("discovery-")
    assert captured["evidence"].run_dir.name == captured["run_id"]
    assert captured["vendor_product"] == "servicing_console"


def test_main_sanitizes_malformed_input_errors(tmp_path, capsys):
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(checkout_artifact().model_dump_json())
    inputs_path = tmp_path / "inputs.json"
    inputs_path.write_text('{"pin": "hunter2"')

    assert main(["replay", "--artifact", str(artifact_path), "--inputs", str(inputs_path)]) == 2
    error = capsys.readouterr().err
    assert "inputs" in error
    assert "hunter2" not in error


def test_main_sanitizes_invalid_artifact_errors(tmp_path, capsys):
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text('{"name": "../hunter2"}')
    inputs_path = tmp_path / "inputs.json"
    inputs_path.write_text("{}")

    assert main(["replay", "--artifact", str(artifact_path), "--inputs", str(inputs_path)]) == 2
    error = capsys.readouterr().err
    assert "artifact" in error
    assert "hunter2" not in error


def test_replay_uses_a_unique_evidence_directory_per_execution(tmp_path, monkeypatch):
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(checkout_artifact().model_dump_json())
    inputs_path = tmp_path / "inputs.json"
    inputs_path.write_text(json.dumps({"product": "Blue Top", "quantity": 1,
                                       "email": "a@b.com", "password": "pw"}))
    captured = _capture_replay(monkeypatch)
    monkeypatch.setattr(cli, "EVIDENCE_ROOT", str(tmp_path / "evidence"))

    command = ["replay", "--artifact", str(artifact_path), "--inputs", str(inputs_path)]
    assert main(command) == 0
    assert main(command) == 0
    assert captured[0]["evidence"].run_dir != captured[1]["evidence"].run_dir
    assert captured[0]["evidence"].run_dir.parent == tmp_path / "evidence"


def test_discovery_refuses_to_overwrite_an_artifact(tmp_path, monkeypatch, capsys):
    inputs_path = tmp_path / "inputs.json"
    inputs_path.write_text(json.dumps({"product": "Blue Top"}))
    out = tmp_path / "out"
    out.mkdir()
    existing = out / "discover_test.json"
    existing.write_text("keep")

    class Runner:
        def __init__(self, **kwargs):
            pass

        def set_runtime_values(self, values):
            pass

        def run(self):
            return checkout_artifact(name="discover_test")

    anthropic = ModuleType("anthropic")
    anthropic.Anthropic = lambda: object()
    monkeypatch.setitem(sys.modules, "anthropic", anthropic)
    import automation.discovery as discovery
    monkeypatch.setattr(discovery, "DiscoveryRunner", Runner)
    monkeypatch.setattr(cli, "PlaywrightSurface", lambda **_: _SurfaceContext())

    assert main([
        "discover", "--goal", "test", "--capability", "discover_test",
        "--inputs", str(inputs_path), "--out", str(out),
    ]) == 2
    assert existing.read_text() == "keep"
    assert "already exists" in capsys.readouterr().err


def test_discovery_collision_refusal_is_atomic(tmp_path, monkeypatch):
    inputs_path = tmp_path / "inputs.json"
    inputs_path.write_text(json.dumps({"product": "Blue Top"}))
    out = tmp_path / "out"
    target = out / "discover_test.json"

    class Runner:
        def __init__(self, **kwargs):
            pass

        def set_runtime_values(self, values):
            pass

        def run(self):
            return checkout_artifact(name="discover_test")

    anthropic = ModuleType("anthropic")
    anthropic.Anthropic = lambda: object()
    monkeypatch.setitem(sys.modules, "anthropic", anthropic)
    import automation.discovery as discovery
    monkeypatch.setattr(discovery, "DiscoveryRunner", Runner)
    monkeypatch.setattr(cli, "PlaywrightSurface", lambda **_: _SurfaceContext())

    original_open, original_write = Path.open, Path.write_text

    def race_open(path, mode="r", *args, **kwargs):
        if path == target and mode == "x":
            original_write(path, "winner")
        return original_open(path, mode, *args, **kwargs)

    def race_write(path, data, *args, **kwargs):
        if path == target:
            original_write(path, "winner")
        return original_write(path, data, *args, **kwargs)

    monkeypatch.setattr(Path, "open", race_open)
    monkeypatch.setattr(Path, "write_text", race_write)

    assert main([
        "discover", "--goal", "test", "--capability", "discover_test",
        "--inputs", str(inputs_path), "--out", str(out),
    ]) == 2
    assert target.read_text() == "winner"


def test_sensitive_invalid_input_uses_a_generic_detail(tmp_path):
    artifact = checkout_artifact()
    artifact.inputs["quantity"] = InputSpec(type="integer", min_value=1, sensitive=True)
    result = ReplayRunner(
        artifact=artifact,
        policy=PolicyEngine(Policy(
            allowed_origins=[{"scheme": "https", "host": "automationexercise.com"}],
            allowed_actions=["navigate", "click", "fill", "select", "extract", "assert"],
        )),
        evidence=EvidenceWriter(tmp_path, "run", {"quantity"}),
        surface=FakeSurface(),
    ).run({"email": "a@b.com", "password": "pw", "product": "Blue Top", "quantity": 0})

    assert result.failure.observed == "quantity: invalid value"
