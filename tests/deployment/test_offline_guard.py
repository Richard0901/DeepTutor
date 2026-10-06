"""Tests for the clinical_offline startup guard."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.deployment.offline import (
    CLINICAL_OFFLINE_MODE,
    assert_clinical_offline_ready,
    deployment_mode,
    enforce_offline_gates_if_configured,
)


def _write_auth(settings: Path, enabled: bool) -> Path:
    settings.mkdir(parents=True, exist_ok=True)
    (settings / "auth.json").write_text(
        json.dumps({"version": 1, "enabled": enabled, "username": "admin", "password_hash": ""}),
        encoding="utf-8",
    )
    return settings


def test_guard_passes_when_auth_enabled(tmp_path):
    settings = _write_auth(tmp_path / "settings", enabled=True)
    assert_clinical_offline_ready(settings)  # no exception


def test_guard_rejects_disabled_auth(tmp_path):
    settings = _write_auth(tmp_path / "settings", enabled=False)
    with pytest.raises(RuntimeError, match="refuses to start"):
        assert_clinical_offline_ready(settings)


def test_guard_rejects_missing_auth_file(tmp_path):
    with pytest.raises(RuntimeError, match="missing"):
        assert_clinical_offline_ready(tmp_path / "settings")


def test_guard_rejects_malformed_auth_file(tmp_path):
    settings = tmp_path / "settings"
    settings.mkdir(parents=True)
    (settings / "auth.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="parse"):
        assert_clinical_offline_ready(settings)


def test_enforce_is_noop_in_other_modes(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPTUTOR_DEPLOYMENT_MODE", raising=False)
    # No settings at all — a no-op must not raise outside the offline mode.
    enforce_offline_gates_if_configured(tmp_path)


def test_enforce_applies_gate_in_offline_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPTUTOR_DEPLOYMENT_MODE", CLINICAL_OFFLINE_MODE)
    with pytest.raises(RuntimeError):
        enforce_offline_gates_if_configured(tmp_path / "settings")
    settings = _write_auth(tmp_path / "settings", enabled=True)
    enforce_offline_gates_if_configured(settings)
    assert deployment_mode() == "clinical_offline"
