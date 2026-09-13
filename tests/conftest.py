"""Shared fixtures. Keeps the offline suite from touching the real evidence tree."""
import pytest

import automation.cli as cli


@pytest.fixture(autouse=True)
def _evidence_root_in_tmp(tmp_path, monkeypatch):
    """CLI tests call main(); evidence they create must land under tmp_path."""
    monkeypatch.setattr(cli, "EVIDENCE_ROOT", str(tmp_path / "evidence"))
    yield
