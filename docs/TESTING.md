# Testing and live acceptance

Last consolidated: 2026-11-10, release 0.1.10. This document separates automated
checks from behavior that still needs evidence on the target HA installation.
Release history belongs in the [changelog](../pi_butler/CHANGELOG.md); runtime
constraints are described in [architecture](ARCHITECTURE.md).

## Local checks

Run from the repository root with Python 3.11 or later, Node and uv available:

```sh
uv sync --project pi_butler --locked
PYTHONPATH=pi_butler/src uv run --project pi_butler --locked python -m unittest discover -s pi_butler/tests -v
node --test pi_butler/tests/test_browser_policy.mjs pi_butler/tests/test_starters.mjs
uv run --project pi_butler --locked python pi_butler/tests/check_metadata.py
uv run --project pi_butler --locked python -m compileall -q pi_butler/src
git diff --check
```

Tests cover policy matching and denied targets, permission persistence and stale
saves, bounded/redacted upstream reads, MCP framing, ingress routing and method
boundaries, Git preparation/delivery failure paths, setup/house notes and workflow
launch contracts. Fake HA/forge responses and temporary bare repositories do not
prove behavior with live services.

## Image and runtime checks

With Docker available, run the same checks as the
[CI workflow](../.github/workflows/check.yaml):

```sh
docker build --platform linux/amd64 -t pi-butler:test pi_butler
docker run --rm --entrypoint /bin/bash pi-butler:test -c 'pi --version && pi-web --version && gh --version && glab --version && pi-web-sessiond --check-runtime'
docker run --rm --entrypoint /opt/venv/bin/python3 -v "$PWD/pi_butler/tests:/tests:ro" pi-butler:test -m unittest discover -s /tests -v
docker run --rm --user 1000:1000 --entrypoint node -v "$PWD/pi_butler/tests:/tests:ro" pi-butler:test /tests/plugin_smoke.mjs
docker run --rm --user 1000:1000 --entrypoint node -v "$PWD/pi_butler/tests:/tests:ro" pi-butler:test /tests/marketplace_smoke.mjs
docker run --rm --user 1000:1000 --entrypoint node -v "$PWD/pi_butler/tests:/tests:ro" pi-butler:test /tests/model_status_smoke.mjs
uv run --project pi_butler --locked bash pi_butler/tests/container_smoke.sh
```

The image checks native node-pty loading and SDK resolution. Plugin smoke loads
bundled extensions without model calls. Marketplace smoke exercises installation,
restart, discovery, version upgrades and preservation of user choices. Model
readiness smoke checks synthetic subscription/API-key credentials against the
pinned SDK with HTTP requests blocked and no real credentials. Container
smoke uses a disposable Docker volume and placeholder credential; it checks startup,
actual Pi Web project registration, MCP, protected file/process/socket boundaries,
shutdown and storage-limit recovery without contacting HA. It does not replace
Supervisor protection-mode testing.

## Recorded evidence

| Area | Evidence and limit |
| --- | --- |
| HA installation | Successful installation was reported after the 0.1.2 build correction. This does not establish acceptance of later features. |
| Linux container baseline | [CI run 42814062685](https://github.com/stieglma/ha-pi-butler/actions/runs/42814062685) passed amd64 build/runtime and boundary checks for commit cf8d739. Later local Colima builds and full container smoke also passed before Phase 6. |
| Release 0.1.10 local checks | 88 Python tests, 12 Node tests, metadata and whitespace checks passed. These are a dated snapshot, not a required permanent test count. |
| Phase 6 browser checks | All five forms created/submitted/opened conversations using simulated APIs under an ingress prefix; local-time conversion and a 390px layout were checked. Disabled skills, failed catalogs and interrupted submissions have automated coverage. |
| Marketplace | Actual pinned SDK/marketplace lifecycle smoke passed locally, including plugin upgrades and user disable/removal preservation. |
| Current live behavior | Starter launch, automation investigations and HAGHS interpretation still require target-installation evidence. The Phase 6 image was not rebuilt locally before release; no subsequent CI result is asserted here. |

Older experiments and superseded failures remain available in Git history. Do not
carry an old passing build forward as proof for a newer commit or mark a live check
passed solely because mocks or source-contract inspection pass.

## Live acceptance checklist

Original target: amd64 HAOS VM on Proxmox, Core 2026.11.1, Supervisor 2026.10.5,
HAOS 18.4. Record actual installed versions and commit/release for each test. Keep
protection mode enabled. The items below remain open until specific evidence is
recorded; some may already work but lack a recorded acceptance result.

| Check | Evidence needed |
| --- | --- |
| Current release startup | Build/install/start, native terminal runtime and critical services remain healthy. |
| Ingress and terminal | Real ingress prefix, assets, HTTP/WebSockets, terminal input/resize and reconnect work; direct non-ingress requests remain denied. |
| No-login onboarding | UI opens without provider/Git login; setup reports readiness accurately and projects register once ready. |
| Credential boundary | Agent and terminal cannot read options/service credentials, inspect protected process data, modify policy/code or gain capabilities. Pi cannot reach the permission-management socket. |
| HA reads and diagnostics | States, registries, history, calendar reads, automation definitions/traces and Core/app logs work with real Supervisor authority; missing/truncated evidence is reported. |
| Write policy | Default denial; entity/domain/direct-label OR grants; exclusions, membership changes, mixed denied targets and distinct automation-trigger rights behave correctly. |
| Permission and notes editors | Direct saves, immediate policy application, stale-edit rejection and persistence work through actual HA ingress. |
| Workflow starters | All five starters open the intended new conversation with the correct skill/context; submission failures preserve a usable recovery path. |
| Investigations and HAGHS | Explain/debug/incident skills produce evidence-backed results; health checks work with HAGHS present, absent or unavailable and respect exclusions/input gaps. |
| Provider and forge authentication | Actual provider login, GitHub/GitLab CLI auth, SSH/HTTPS/custom hosts and correctly targeted push/PR/MR delivery work; failures preserve work. |
| Persistence and restore | Credentials, notes, permissions, workspaces and saved sessions survive restart/update/replacement and a full HA backup/restore. Active processes need not survive restart. |
| Recovery and responsiveness | Dirty/divergent work and storage-limit shutdown preserve files; large-workspace accounting leaves the UI responsive on the target host. |

For boundary checks, run [boundary_probe.py](../pi_butler/tests/boundary_probe.py)
as the Pi identity with the same groups/no-new-privileges settings as the app.
[container_smoke.sh](../pi_butler/tests/container_smoke.sh) shows the invocation.
Also check from the actual Pi Web terminal; the probe is not exhaustive.

Cache reuse measurements and Supervisor build-cache retention remain unmeasured
optimization checks, not release acceptance requirements. CI cache import/export
was deliberately skipped; optional download-cache mounts have not been implemented.
