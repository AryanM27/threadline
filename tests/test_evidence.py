import json
from pathlib import Path

from automation.evidence import EvidenceWriter
from automation.models import CapabilityArtifact
from tests.fakes import checkout_artifact


def test_events_are_redacted_before_they_hit_disk(tmp_path):
    w = EvidenceWriter(root=tmp_path, run_id="run-1", sensitive_names={"email"})
    w.event("fill", step_id="s1", email="a@b.com", password="hunter2", product="Blue Top")

    lines = (tmp_path / "run-1" / "events.jsonl").read_text().strip().splitlines()
    record = json.loads(lines[0])
    assert record["email"] == "[REDACTED]"
    assert record["password"] == "[REDACTED]"
    assert record["product"] == "Blue Top"
    assert record["type"] == "fill"
    assert "ts" in record


def test_each_event_is_one_line(tmp_path):
    w = EvidenceWriter(root=tmp_path, run_id="run-1", sensitive_names=set())
    w.event("a", n=1)
    w.event("b", n=2)
    lines = (tmp_path / "run-1" / "events.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2


def test_screenshot_paths_are_unique_and_inside_the_run(tmp_path):
    w = EvidenceWriter(root=tmp_path, run_id="run-1", sensitive_names=set())
    first = w.screenshot_path("before")
    second = w.screenshot_path("before")
    assert first != second
    assert str(tmp_path / "run-1") in first


def test_screenshot_paths_in_evidence_are_relative_to_the_repository(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    writer = EvidenceWriter(tmp_path, "run-x", set())
    assert not Path(writer.screenshot_path("failure")).is_absolute()


def test_written_json_is_redacted(tmp_path):
    w = EvidenceWriter(root=tmp_path, run_id="run-1", sensitive_names={"email"})
    w.write_json("result.json", {"email": "a@b.com", "status": "success"})
    data = json.loads((tmp_path / "run-1" / "result.json").read_text())
    assert data["email"] == "[REDACTED]"
    assert data["status"] == "success"


def test_capability_artifact_round_trips_without_redacting_input_definitions(tmp_path):
    artifact = checkout_artifact()
    w = EvidenceWriter(root=tmp_path, run_id="run-1",
                       sensitive_names=artifact.sensitive_input_names())

    path = w.write_json("artifact.json", artifact)

    assert CapabilityArtifact.model_validate_json(path.read_text()) == artifact
