# clinical-offline deployment profile

Clinical deployment profile (minimum viable version, corresponding to the "v0.1.0-governed-baseline" tagging conditions in the Secondary Development Plan §10; the complete 10 hard gates at the service layer are scheduled before G3 first-round pilot).

## File Descriptions

```
configs/clinical-offline/
├── README.md                  # This file
├── compose.clinical-offline.yml  # Deployment Compose (production env + runtime hardening)
└── settings/                  # Settings templates (after first boot, overwrite/make changes as directed to the same-named files in <runtime-home>/data/user/settings/)
    ├── auth.json              # Authentication enforced enabled (enabled: true), cookie_secure: true
    ├── main.yaml              # tools.web_search.enabled: false
    ├── interface.json         # Optional tools panel removed web_search/paper_search/imagegen/videogen
    ├── model_catalog.json     # Model directory only keeps local providers (Ollama placeholder); search/voice/image all empty
    ├── mcp.json               # MCP registry empty
    ├── document_parsing.json  # Parsing engine text_only; MinerU local mode with token empty
    └── pageindex.json         # Cloud PageIndex key empty
```

## Deployment Steps

1. Start the container once per the normal process, so `ensure_runtime_settings_files()` generates default settings files;
2. Copy (or item-by-item merge) the seven files from this directory to `<runtime-home>/data/user/settings/`;
3. Set an administrator password in `auth.json` (or leave `password_hash` empty on first boot, and have the first registrant become the administrator);
4. Set the environment variable `DEEPTUTOR_DEPLOYMENT_MODE=clinical_offline` and restart—the startup guard will validate that authentication is enabled, and **refuse to start if authentication is not enabled**;
5. Fill in the local model endpoints in `model_catalog.json` (default placeholder `http://ollama:11434/v1`);

## Boundaries and Declarations (Must-read)

- **Application-layer settings are only defense-in-depth**. The final line of defense for egress denial must be implemented at the host firewall / VM security group / Kubernetes NetworkPolicy, with the default deny-all outbound traffic for backend, frontend, and sandbox runner containers, and only allow access to the intranet LLM/embedding/database addresses. This repository's compose does not and cannot guarantee network egress.
- Incomplete items (scheduled before G3): MCP/Skill Hub/partners service-level hard guards, cloud parsing rejection guards, local-only model allowlist hard validation, packet-capture assertions under broken-network conditions. Under the current minimum version, the above capabilities rely on empty config + network isolation; do not rely on application-layer interception alone.
- `DEEPTUTOR_VERSION_CHECK_ENABLED=0` and `DEEPTUTOR_EXTRAS` unset (runtime package installation prohibited) have been written into the compose; all dependencies must be pre-installed during the image build phase.
- Before deployment, rotate/clear the API keys ever used during the development phase (once stored in the local `data/user/settings/model_catalog.json`).
