"""``clinical_offline`` deployment mode: fail-closed startup guard.

This is the minimal-viable boundary (G0' scope).  When the deployment runs
with ``DEEPTUTOR_DEPLOYMENT_MODE=clinical_offline`` the application refuses
to start unless authentication is enabled in the effective settings — the
plan's security gate "生产环境认证强制开启".

Deliberately out of scope here (tracked as pre-G3 tasks, plan §10 items
1-9): local-only model allowlists, MCP/Skill Hub/partners service guards,
cloud-parser rejection and blocked-egress tests.  Network-level egress
denial must be enforced by the host or network policy; application settings
are defense-in-depth only — see ``configs/clinical-offline/README.md``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

CLINICAL_OFFLINE_MODE = "clinical_offline"


def deployment_mode() -> str:
    return os.environ.get("DEEPTUTOR_DEPLOYMENT_MODE", "").strip()


def default_settings_dir() -> Path:
    from deeptutor.multi_user.paths import ADMIN_WORKSPACE_ROOT

    return Path(ADMIN_WORKSPACE_ROOT) / "user" / "settings"


def assert_clinical_offline_ready(settings_dir: str | Path | None = None) -> None:
    """Raise ``RuntimeError`` unless auth is enabled in the settings files.

    ``settings_dir`` is exposed for tests; production resolves the runtime
    settings directory the same way ``load_auth_settings()`` does.
    """
    directory = Path(settings_dir) if settings_dir is not None else default_settings_dir()
    auth_file = directory / "auth.json"
    if not auth_file.exists():
        raise RuntimeError(
            f"clinical_offline mode requires {auth_file} with {{\"enabled\": true}}; "
            "the file is missing (plan §10 gate 4: 生产环境认证强制开启)"
        )
    try:
        settings = json.loads(auth_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"clinical_offline mode could not parse {auth_file}: {exc}") from exc
    if not settings.get("enabled"):
        raise RuntimeError(
            "clinical_offline mode refuses to start with authentication disabled: "
            f"set \"enabled\": true in {auth_file} (plan §10 gate 4)"
        )


def enforce_offline_gates_if_configured(settings_dir: str | Path | None = None) -> None:
    """Entry point called during application startup; no-op in other modes."""
    if deployment_mode() == CLINICAL_OFFLINE_MODE:
        assert_clinical_offline_ready(settings_dir)
