"""Run evidence: redacted JSONL events, screenshots, and result documents.

Redaction happens here, at the single point where data leaves memory for
disk. Putting it anywhere else would mean every new caller has to remember.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from itertools import count
from pathlib import Path
from typing import Any

from automation.models import CapabilityArtifact
from automation.policy import redact


class EvidenceWriter:
    def __init__(self, root: str | Path, run_id: str, sensitive_names: set[str]):
        self.run_dir = Path(root) / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._events = self.run_dir / "events.jsonl"
        self._sensitive = set(sensitive_names)
        self._counter = count(1)

    def event(self, type: str, **fields: Any) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": type,
            **redact(fields, self._sensitive),
        }
        with self._events.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def screenshot_path(self, label: str) -> str:
        return str(self.run_dir / f"{next(self._counter):03d}-{label}.png")

    def write_json(self, name: str, obj: Any) -> Path:
        path = self.run_dir / name
        payload = obj.model_dump() if hasattr(obj, "model_dump") else obj
        safe_payload = payload if isinstance(obj, CapabilityArtifact) else redact(
            payload, self._sensitive
        )
        path.write_text(json.dumps(safe_payload, indent=2),
                        encoding="utf-8")
        return path
