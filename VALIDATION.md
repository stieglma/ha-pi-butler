# Validation record

Date: 2026-11-10. Status: local checks and amd64 container CI pass; live HA acceptance pending.

## Completed locally

- 44 Python tests pass on Python 3.14.6/macOS, including:
  - policy default denial, OR/AND matching, exclusion precedence, changing labels,
    inherited domain membership, independent automation-trigger grants;
  - mixed denied/unknown targets execute zero upstream writes, embedded target
    rejection, catalog/data validation and calendar capability checks;
  - bounded/redacted responses, pagination, finite routes, unavailable registries;
  - actual HTTP/WebSocket test server checks upstream authentication, response
    byte limits and refusal to follow redirects;
  - actual MCP stdio framing, oversized-frame recovery, initialization/errors
    and full assembly of chunked large tool responses;
  - Git against temporary local bare remotes: non-main destination, worktrees,
    syntax validation, remote divergence/dirty-work preservation, PR auth failure
    without destination push and incorrect PR target rejection;
  - ingress denial despite spoofed headers, plus real HTTP/WebSocket proxying
    that preserves public Host/Origin;
  - retention keeps fresh files and never follows symlinks to external artifacts.
- HA YAML metadata consistency check, Python compilation and shell syntax pass.
- npm lock resolves and clean published-package installation succeeds in an
  isolated temporary directory; npm reports zero known vulnerabilities at check.
- Pi reports 1.5.1; Pi Web reports 1.202611.1; terminal runtime preflight passes.
- Started published Pi Web/sessiond with isolated home/config/data paths and no
  provider login: web HTTP 200, daemon Unix socket and terminal plugin activation
  observed; both stop on SIGTERM. This was on macOS, not inside the HA image.
- glab 1.128.0 macOS archive help confirms documented device-login, storage,
  Git-helper and MR flags; actual forge authentication remains untested.
- Base image digest resolved; amd64 gh/glab archives downloaded and SHA-256 recorded.

## Initial local validation limits

At initial implementation, Docker was absent in this workspace. The Linux image build, privilege boundary
probe, container startup/shutdown test and CI workflow were initially written but
not executed. Subsequent successful remote CI results are recorded below. No HA connection or authentication credentials were available. None of
the following live checks is claimed to pass.

## HA integration checklist

Use the target environment from PLAN.md (amd64 HAOS VM; Core 2026.11.1,
Supervisor 2026.10.5, HAOS 18.4). Record date, actual versions, evidence and fixes.
Keep protection mode enabled throughout.

| Check | Expected evidence | Result |
| --- | --- | --- |
| Build/install/start | Pinned npm tools and native node-pty load; all four critical processes remain running | pending |
| Ingress prefix | UI/static assets/API work under actual ingress prefix | pending |
| PTY/WebSocket | Terminal input/output and resize work; reconnect resumes view | pending |
| Browser disconnect | Active server-side agent work continues | pending |
| No repository/login | UI and terminal reachable; setup reports optional/pending | pending |
| File boundary | Pi cannot read options, service directory or credential process files; cannot edit policy/startup/image code | pending |
| Process boundary | Pi/terminal env has no Supervisor credential; root/service environ/fd/mem inaccessible; no capabilities or setuid escalation | pending |
| Socket boundary | Pi can use narrow tools, cannot replace service socket; ingress identity has no HA credential | pending |
| Direct ingress | Another app's direct request is 403 even with forged headers; loopback backend inaccessible externally | pending |
| HA broad reads | State, config, all registries, services, bounded history/calendar reads | pending |
| Logs | Core /core/logs works with homeassistant role; app logs survive rotation and redact known secrets | pending |
| Default denial | State-changing calls fail without configured grant | pending |
| Grants | Entity/domain/direct-label AND matching and exclusions; new entities inherit; label removal revokes | pending |
| Mixed targets | One denied or unknown target rejects all before upstream write | pending |
| Catalog boundary | Global/admin/template/event/script/scene and embedded target attempts fail | pending |
| Automation | Control permits enable/disable, manual trigger needs separate capability | pending |
| Registry churn | Observe race behavior and document limits; resolution errors deny | pending |
| Calendar | Actual calendar.create_event advertised/support flag; integration validates dates/timezones | pending |
| Forge auth | gh/glab headless login with HTTPS helpers; SSH/custom ports/known_hosts | pending |
| Delivery | Non-main push and exact PR/MR base/head; auth failure keeps work; no implicit merge/reload | pending |
| Persistence | Restart/update/container replacement preserve credentials, work and saved sessions | pending |
| Backups | Full app backup restore recovers credentials/worktrees/saved sessions | pending |
| Recovery | Dirty/divergent repository and storage threshold recovery preserve work | pending |

Run `tests/boundary_probe.py` as the pi identity from a trusted HA/container
maintenance context with the same groups/no-new-privileges as the app. It never
prints credential values. CI's `tests/container_smoke.sh` demonstrates the exact
identity invocation. Also inspect attempted process FD access and policy bypasses
from the actual Pi Web terminal; the probe is not exhaustive exploit testing.

## Known limits

- HA runtime installation, Supervisor role authority and actual log coverage are
  pending verification; milestone 3 is incomplete, and milestone 4 depends on it.
- Registry resolution and service execution are not atomic; authorized HA actions
  can have indirect effects, and HA can partially execute after authorization.
- Calendar supports generic create_event only, not integration-specific update/delete.
- Whole-registry API responses can exceed the configured limit before local paging.
- Log redaction is best effort; diagnostic text is untrusted.
- Storage enforcement checks once a minute and stops processes; it is not a hard
  quota. User sessions and Git work are never automatically pruned.
- Forge delivery tests cover Git behavior and mocked CLI results; real GitHub,
  GitLab and self-hosted auth/PR/MR flows remain pending.
- Protection resists ordinary shell tools, not kernel exploits or a compromised
  trusted service. Do not relax the single-app authority boundary to fix failures.

## uv migration validation

Replaced requirements.txt with pyproject.toml and uv.lock. Direct dependencies
remain aiohttp 3.13.2 and PyYAML 6.0.3; the universal lock preserves the prior
transitive versions, including typing-extensions for Python 3.11/3.12.
Locked uv sync and all 44 tests pass on Python 3.14.6 and Python 3.11.15 locally.
Metadata, source compilation and lock consistency checks pass. Docker and CI
now install from the committed lock with pinned uv 0.11.28. Docker execution
remains pending because Docker is unavailable here.

## Bundled packages validation (0.1.1)

- 49 Python tests pass on Python 3.11, including five profile tests: settings and
  resource-filter preservation, idempotent upgrades, respecting removals, invalid
  input rejection, and real-file initialization/symlink protection.
- Exact npm pins resolve with no known audit vulnerabilities at check time.
- All five packages load through Pi 1.5.1 on both local Node 26.12.1 and pinned
  Node 24.15.0: 10 registered tools, 38 commands and 4 discovered skills. No
  model/provider calls are made by this smoke check.
- Fresh profile initialization followed by `pi list` shows all five local sources.
  Pi Web/sessiond start on Node 24.15.0 with that profile, returning HTTP 200,
  creating the daemon socket and completing global provider baseline bootstrap.
- CI now loads every extension as uid 1000 in the Linux image and checks default
  registrations during startup smoke. Linux Docker/HA execution is still pending.
- Structured question interaction, terminal footer rendering, hosted progress UI,
  real delegated model work and custom marketplace imports need live validation.
  No custom marketplace content has been created or remote marketplace enabled.

## First HA build attempt and 0.1.2 correction

Thomas's HA Supervisor reached the amd64 image build for 0.1.1 but failed at
`groupadd: not found` after successful apt installation. GitHub Actions reproduced
the same failure. Docker's explicit PATH omitted /usr/sbin, where Debian installs
account-management commands. Version 0.1.2 restores the administrative PATH and
explicitly installs passwd. HA runtime acceptance remains pending.

GitHub Actions run 42813700473 built the 0.1.2 image successfully and passed the
Linux Python tests, plugin smoke, startup/HTTP checks, credential boundary probe,
ingress denial and clean shutdown. The job then failed only removing the host
bind-mounted test data, which was correctly root/service-owned by the app.
The smoke fixture now uses a disposable Docker volume so CI cleanup does not
need to remove protected files through the runner's unprivileged filesystem.

## Passed amd64 container CI for 0.1.2

[GitHub Actions run 42814062685](https://github.com/stieglma/ha-pi-butler/actions/runs/42814062685)
completed successfully for commit cf8d739 on 2026-11-10. Both jobs passed:

- Full amd64 Docker build using the pinned Node and uv images.
- Python tests, metadata consistency and source compilation on the Linux runner.
- Python tests inside the built image and all five extensions loaded as uid 1000.
- Pi/Pi Web/gh/glab versions and Pi Web's native terminal runtime preflight.
- Fresh startup, default package registration, HTTP serving and daemon socket.
- Pi-user credential/file/process/capability boundary probe and Unix socket access.
- Direct ingress rejection, SIGTERM shutdown and Docker-volume fixture cleanup.

This replaces the earlier unexecuted Docker/CI status. Actual HA protection-mode
behavior, real Supervisor/Core APIs, ingress browser/terminal interactions,
authentication/delivery and backup/restore checks remain pending.
