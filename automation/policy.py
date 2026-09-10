"""Allowlist enforcement and redaction.

Origin checks parse the URL and compare scheme, host, and port exactly.
Substring matching is never used: "automationexercise.com.evil.io" contains
the allowed host but is a different origin, and that is precisely the case
a substring check gets wrong.
"""
from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict

SECRET_KEY_HINTS = ("password", "passwd", "secret", "token", "api_key",
                    "apikey", "authorization", "cookie", "credential")
REDACTED = "[REDACTED]"


class PolicyDenied(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class AllowedOrigin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scheme: str
    host: str
    port: int | None = None
    dev_only: bool = False


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allowed_origins: list[AllowedOrigin]
    denied_route_patterns: list[str] = []
    allowed_actions: list[str]


def load_policy(path: str | Path) -> Policy:
    return Policy(**json.loads(Path(path).read_text()))


class PolicyEngine:
    def __init__(self, policy: Policy, allow_dev_origins: bool = True):
        self._policy = policy
        self._allow_dev = allow_dev_origins

    def check_url(self, url: str) -> None:
        """Raise PolicyDenied unless the URL is on an allowed origin and
        outside every denied route pattern."""
        parsed = urlparse(url)
        for origin in self._policy.allowed_origins:
            if origin.dev_only and not self._allow_dev:
                continue
            if parsed.scheme != origin.scheme:
                continue
            if (parsed.hostname or "") != origin.host:
                continue
            if parsed.port != origin.port:
                continue
            break
        else:
            raise PolicyDenied("policy_origin_denied", f"origin not allowed: {url}")

        path = parsed.path or "/"
        for pattern in self._policy.denied_route_patterns:
            if fnmatch.fnmatch(path, pattern):
                raise PolicyDenied("policy_route_denied",
                                   f"route {path} matches denied pattern {pattern}")

    def check_action(self, action: str) -> None:
        if action not in self._policy.allowed_actions:
            raise PolicyDenied("policy_action_denied", f"action not allowed: {action}")

    def needs_human(self, risk: str) -> bool:
        return risk == "requires_human"


def redact(value: Any, sensitive_names: set[str]) -> Any:
    """Return a copy with sensitive values replaced. Never mutates the input.

    A key is redacted when it is named in the artifact's sensitive inputs or
    when it looks like a secret. Redacting by key rather than by value means
    a secret is hidden even when the value is empty or unexpected.
    """
    lowered = {n.lower() for n in sensitive_names}

    def _walk(node: Any) -> Any:
        if isinstance(node, dict):
            out = {}
            for key, item in node.items():
                k = str(key).lower()
                if k in lowered or any(hint in k for hint in SECRET_KEY_HINTS):
                    out[key] = REDACTED
                else:
                    out[key] = _walk(item)
            return out
        if isinstance(node, (list, tuple)):
            return [_walk(item) for item in node]
        return node

    return _walk(value)
