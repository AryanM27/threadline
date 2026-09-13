"""Saved artifacts rendered as callable tool schemas.

The artifact already carries the contract an agent needs, so this is a
projection of existing types rather than new modeling. Invocation runs the
ordinary replay path; the catalog holds no execution authority of its own.
"""
from __future__ import annotations

import json
from pathlib import Path

from automation.models import CapabilityArtifact

_JSON_TYPES = {"string": "string", "integer": "integer",
               "number": "number", "boolean": "boolean"}


class CapabilityCatalog:
    def __init__(self, artifacts_dir: str | Path):
        self._dir = Path(artifacts_dir)

    def _load_all(self) -> dict[str, CapabilityArtifact]:
        out = {}
        for path in sorted(self._dir.glob("*.json")):
            art = CapabilityArtifact(**json.loads(path.read_text()))
            if art.name in out:
                raise ValueError(f"duplicate capability name {art.name!r}")
            out[art.name] = art
        return out

    def get(self, name: str) -> CapabilityArtifact:
        artifacts = self._load_all()
        if name not in artifacts:
            raise KeyError(f"no capability named {name!r} in {self._dir}")
        return artifacts[name]

    def list(self) -> list[dict]:
        return [{"name": a.name, "description": a.description,
                 "artifact_version": a.artifact_version,
                 "provenance": a.provenance,
                 "derived_from": a.derived_from}
                for a in sorted(self._load_all().values(), key=lambda a: a.name)]

    def tool_schema(self, name: str) -> dict:
        art = self.get(name)
        properties, required = {}, []
        for input_name, spec in art.inputs.items():
            prop = {"type": _JSON_TYPES[spec.type]}
            if spec.min_value is not None:
                prop["minimum"] = spec.min_value
            if spec.max_length is not None:
                prop["maxLength"] = spec.max_length
            if spec.pattern is not None:
                prop["pattern"] = spec.pattern
            if spec.sensitive:
                # Signals a value the caller supplies but that is never
                # echoed back, logged, or stored.
                prop["writeOnly"] = True
            properties[input_name] = prop
            if spec.required:
                required.append(input_name)

        outputs = ", ".join(f"{n} ({s.type})" for n, s in art.outputs.items()) or "none"
        outcomes = {o.code for o in art.business_outcomes}
        outcomes.update(o.code for step in art.steps for o in step.business_outcomes)
        if any(step.risk == "requires_human" for step in art.steps):
            outcomes.add("cancelled_by_human")
        outcomes = ", ".join(sorted(outcomes)) or "none"
        return {
            "name": art.name,
            "description": (f"{art.description}\n"
                            f"Returns: {outputs}.\n"
                            f"Known business outcomes: {outcomes}."),
            "input_schema": {"type": "object", "properties": properties,
                             "required": sorted(required)},
        }
