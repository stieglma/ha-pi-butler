# Testing and live acceptance

Release baseline: 1.0.0. This document separates automated
checks from behavior that still needs evidence on the target HA installation.
Release history belongs in the [changelog](../pi_butler/CHANGELOG.md); runtime
constraints are described in [architecture](ARCHITECTURE.md).

## Local checks

Run from the repository root with Python 3.11 or later, Node and uv available:

```sh
uv sync --project pi_butler --locked
PYTHONPATH=pi_butler/src uv run --project pi_butler --locked python -m unittest discover -s pi_butler/tests -v
node --test pi_butler/tests/test_browser_policy.mjs pi_butler/tests/test_starters.mjs pi_butler/tests/test_settings.mjs
uv run --project pi_butler --locked python pi_butler/tests/check_metadata.py
uv run --project pi_butler --locked python -m compileall -q pi_butler/src
git diff --check
```

Tests cover policy matching and denied targets, permission persistence and stale
saves, bounded/redacted upstream reads, MCP framing, ingress routing and method
boundaries, Git preparation/delivery failure paths, setup/house notes and workflow
launch contracts. Fake HA/forge responses and temporary bare repositories do not
prove behavior with live services.

## KNX 1.2.0 lifecycle checks

Local release checks passed 119 Python tests and 18 Node tests, metadata validation
and Python compilation. These checks do not replace the native image and live
acceptance checks below.

The image CI runs `knx_projects_smoke.py`, `knx_api_smoke.py` and
`knx_runtime_smoke.py` using the separate pinned editor Python environment, in
addition to its credential smoke. Run the runtime smoke only in a fresh disposable
container: it creates synthetic files at `/data/knx` and launches the production
headless editor twice as uid 1003 with `--no-connect`. It does not test the firewall
or connect/program any bus device.

Earlier beta.2 evidence: 112 Python unit/integration tests and 12 Node tests passed;
the linux/amd64 image built under emulation and its 112 Python tests passed.
Pinned editor synthetic tests cover paired export/reimport of a public fixture
device, native reopen with an empty catalog, stale permission rejection,
default-denied/granted writes, rollback, and a failed pre-programming checkpoint.
The headless production launcher passed manual-project adoption, initial automatic
checkpoint, denied mutation and reopening after process restart. Browser checks
under an ingress prefix exercised permission save, checkpoint and restore, text
escaping and a 390px layout. These are not live HA/ETS/house-device acceptance.

## Image and runtime checks

On macOS with Colima, ensure the Docker CLI is on `PATH` and Colima is running.
For a Homebrew installation whose Docker CLI is not linked, use:

```sh
export PATH="$(brew --prefix docker)/bin:$PATH"
colima status
export DOCKER_DEFAULT_PLATFORM=linux/amd64
```

This uses the current Docker context. The app remains amd64-only. Image builds,
unit and package tests can run under emulation on Apple Silicon. Mandatory
firewall/full-app startup needs native Linux/amd64: qemu user-mode netlink calls
are unsupported and startup intentionally fails closed. Use native amd64 CI for
the complete image; the native Colima policy probe below tests the same production
firewall code against the real Linux kernel without implying ARM app support.

With Docker available, run the same checks as the
[CI workflow](../.github/workflows/check.yaml):

```sh
docker build --platform linux/amd64 -t pi-butler:test pi_butler
docker run --rm --entrypoint /bin/bash pi-butler:test -c 'pi --version && pi-web --version && gh --version && glab --version && pi-web-sessiond --check-runtime'
docker run --rm --entrypoint /opt/venv/bin/python3 -v "$PWD/pi_butler/tests:/tests:ro" pi-butler:test -m unittest discover -s /tests -v
docker run --rm --user 1000:1000 --entrypoint node -v "$PWD/pi_butler/tests:/tests:ro" pi-butler:test /tests/plugin_smoke.mjs
docker run --rm --user 1000:1000 --entrypoint node -v "$PWD/pi_butler/tests:/tests:ro" pi-butler:test /tests/marketplace_smoke.mjs
docker run --rm --user 1000:1000 --entrypoint node -v "$PWD/pi_butler/tests:/tests:ro" pi-butler:test /tests/model_status_smoke.mjs
docker run --rm --entrypoint /opt/knx/venv/bin/python -e PYTHONPATH=/source -v "$PWD/pi_butler/src:/source:ro" -v "$PWD/pi_butler/tests:/tests:ro" pi-butler:test /tests/knx_editor_auth_smoke.py
uv run --project pi_butler --locked bash pi_butler/tests/firewall_smoke.sh
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
| HA installation | Installation has succeeded on the target host. Full acceptance of the current release remains subject to the checks below. |
| Linux container baseline | [CI run 42814062685](https://github.com/stieglma/ha-pi-butler/actions/runs/42814062685) passed amd64 build/runtime and boundary checks for commit cf8d739. Later local Colima builds and full container smoke also passed before the investigation starters were added. |
| Investigation starter browser checks | All five forms created/submitted/opened conversations using simulated APIs under an ingress prefix; local-time conversion and a 390px layout were checked. Disabled skills, failed catalogs and interrupted submissions have automated coverage. |
| Marketplace | Actual pinned SDK/marketplace lifecycle smoke passed locally, including plugin upgrades and user disable/removal preservation. |
| Current live behavior | Starter launch, automation investigations and HAGHS interpretation still require target-installation evidence. The latest image and live behavior must be checked for the installed release; no subsequent CI result is asserted here. |

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


## KNX acceptance candidate

The optional KNX integration is described in the [user documentation](../pi_butler/DOCS.md#optional-knx-editor-120).
Unit tests cover active-admin identity,
HTTP/WebSocket credentials, finite reads, source paths, gateway IP validation,
and fail-closed firewall setup. `knx_mcp_smoke.py` checks pinned FastMCP JSON/SSE
framing and authentication without a project or GUI. `knx_editor_auth_smoke.py`
runs the production launcher and pinned editor plugin, checks that the managed
UI token accessor cannot disclose the supervisor credential, and verifies that
only that credential authenticates after restarts with empty or user-supplied
settings tokens. It uses loopback only, without a project, GUI session or bus.

The earlier source-location build passed 98 container unit tests, package/runtime
smokes and full app smoke locally and in CI. Do not apply that evidence to the
later mandatory-firewall build: it changes privileges and startup. The current
production policy passed the native Colima kernel probe described below; native
amd64 CI must pass the new firewall smoke and full app smoke for the exact commit.
Actual HAOS/AppArmor, original-project import/export, ingress and hardware support
remain unverified.

`firewall_smoke.sh` creates a disposable IPv4/IPv6 Docker network, with echo
servers inside its test container only. The arbitrary-Python client initially
reaches the endpoints, then is denied as uid 1000/1001, while uid 1003 remains
allowed. Actual kernel rejection counters must increase: a missing route or failed
client is not accepted as proof. The checks cover TCP/UDP and custom gateway ports,
standard port 3671 on an unlisted address, multicast/broadcast, raw-packet/UID/
firewall tampering, atomic rule replacement and rollback, and NET_ADMIN removal.
It then starts the real supervisor without NET_ADMIN and verifies failure before
any agent directory is initialized. The full container smoke grants NET_ADMIN at
creation, asserts PID 1 drops it, and checks all existing credential/process limits.
The test scripts never contact an actual KNX interface.

On Apple Silicon, run the identical rule generator, apply path and kernel probe
using native Linux Python in a disposable toolbox. The following is a kernel
policy test, not a build/runtime test for the amd64 app:

```sh
export PATH="$(brew --prefix docker)/bin:$PATH"
task_firewall_network="butler-native-firewall-$RANDOM-$$"
trap 'docker network rm "$task_firewall_network" >/dev/null 2>&1 || true' EXIT
docker network create --ipv6 --subnet fd4b:4e58:aa31::/64 "$task_firewall_network"
docker run --rm --platform linux/arm64 --cap-add NET_ADMIN \
  --network "$task_firewall_network" -e PYTHONPATH=/source \
  -v "$PWD/pi_butler/src:/source:ro" -v "$PWD/pi_butler/tests:/tests:ro" \
  --entrypoint /bin/sh python:3.11-slim -c \
  'apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends nftables util-linux >/dev/null && python3 /tests/firewall_probe.py'
```

This optional toolbox follows the installed native Python/Debian image; the
production app dependencies and architecture remain pinned separately.

KNX repository source options default to `knx_editor/project.knxproj`. Tests cover
source-location default migration, custom paths, exact selection without fallback,
and rejection of traversal/symlink/nonregular sources. Setup reports presence and
manual import only. `knx.gateway_addresses` must now contain all interface IPs
before KNX can be enabled; the firewall never infers these from mutable repo files.

### Live KNX acceptance

Record the exact installed commit, Core and Supervisor versions. Use a project
copy first and keep Protection mode enabled. Local synthetic checks do not prove
manufacturer compatibility, ETS acceptance or behavior on physical devices.

1. Configure every real gateway address, enable KNX and restart. Verify firewall
   enforcement, the initially disconnected editor, ingress HTTP/WebSockets and
   file upload/download. Check module disable/re-enable and retained working data.
2. Verify admin and non-admin access, including direct editor and file URLs.
   Missing identity or unavailable role lookup must deny access. Check that the
   agent cannot use internal editor ports, credentials or arbitrary upstream tools.
3. Import a project copy, compare devices, parameters, group addresses and object
   links, then export/reimport and compare semantics. Verify protected-project
   password behavior and representative manufacturer-specific functions separately.
4. Exercise finite assistant reads and default-denied/scoped writes, including
   parameter changes that require delete permission. Test concurrent UI/MCP edits,
   checkpoint/export failure, restore, restart/reopening and cold HA backup/restore.
   Confirm history retains at most the latest ten checkpoints after operations,
   subject to age/byte limits, and that failed checkpoints preserve recovery data.
5. Before Git delivery, add the configured editor-only folder to `restart_ignore`
   in the separate HA Git app. Do not exclude folders containing HA entity YAMLs.
   Verify the configured push/PR workflow, exact delivered artifacts, concurrent
   deliveries and preservation of unrelated work after failures.
6. Perform bus/programming tests as a separate controlled step. Verify that a
   failed pre-programming checkpoint blocks programming. Record support for each
   tested device/application version; project restore does not revert bus devices.
