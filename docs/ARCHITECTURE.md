# Architecture and scope

Pi Butler is one amd64 Home Assistant app providing a shared Pi Coding Agent/Pi
Web workspace through HA ingress. A repository and provider login are optional
for opening the UI; agent conversations require model configuration. Installation,
permissions and operation are documented in the [app guide](../pi_butler/DOCS.md).
Runtime inputs are recorded in [VERSIONS.md](../pi_butler/VERSIONS.md).

## Processes and trust boundaries

```text
Browser → HA ingress → ingress adapter → Pi Web + session daemon
                                           → Pi agent / terminal
                                               → private Git workspace
                                               → Git / SSH / gh / glab
                                               → MCP stdio adapter
                                                   → HA access service
                                                       → Supervisor / HA APIs
```

A small root PID 1 supervisor initializes protected storage, launches children
with explicit identities and clean environments, reaps processes and stops the
app on critical service failure. Pi Web, the session daemon, agent and terminal
run as the Pi user (uid 1000). The HA access service runs as uid 1001; ingress
runs as uid 1002. Only the access service receives the Supervisor credential.
Agent-facing processes have no capabilities and cannot modify protected service
code, options or policy storage. A separate storage-accounting worker retains
only DAC override capability to count private files; artifact retention runs as Pi.

The Pi-owned MCP adapter exposes finite tools over a group-protected Unix socket.
It cannot forward arbitrary API requests or save permissions. Ingress reaches
permission management through a separate socket that Pi cannot access. A Pi-owned
onboarding worker registers projects and serves setup status and versioned house
notes through another socket shared with ingress.

Ingress checks the actual connection peer against the Supervisor ingress source,
not forwarded headers. It preserves browser Host/Origin checks while proxying HTTP
and WebSockets to loopback Pi Web. There are no mapped host ports, host networking,
shared live HA configuration folders, Docker socket or required companion app.
Protection mode stays enabled. This boundary targets ordinary agent/terminal
commands; it does not protect against kernel exploits or a compromised trusted
service. Separate identities alone are not proof of isolation; see
[live acceptance checks](TESTING.md#live-acceptance-checklist).

## HA access and investigations

HA reads are broadly available even when writes are disabled. Tools expose bounded
states, registry metadata, history, calendars, automation configuration/traces and
Core/app diagnostics. They paginate where supported, report truncation and apply
best-effort secret redaction. There is no generic URL, template, event or secret-file
forwarder. Whole upstream snapshots can exceed limits before local pagination.

Writes default to denied. Supported operations must match a capability and at
least one entity, domain or directly assigned label selector; selector categories
and rules combine with OR. Exclusions override grants. Automation triggering needs
its own capability. Targets are expanded and every member authorized before a
service call; any unknown or denied member rejects the request. Registry resolution
and invocation are separate operations, so membership can change between them.
Authorized HA calls can have indirect effects or partially execute upstream.

Permissions save atomically through the ingress settings UI, apply immediately
and reject stale edits. They persist in service-private storage. Repository and
resource options remain in HA app configuration.

The bundled local house marketplace owns investigation instructions and persistent
house-memory behavior. Starter forms collect context and launch existing skills
in new scratch-project conversations. Investigations are read-only; health checks
also inspect HAGHS when available. Missing traces, logs or integration data remain
evidence gaps. Marketplace startup updates the local bundle while respecting user
source overrides, disable/removal choices and unrelated settings.

## Git, credentials and deployment

The optional repository is cloned independently into app storage. The Pi user
manages model and Git/forge authentication through existing Pi Web and terminal
flows. Git/SSH/gh/glab credentials are intentionally available to Pi; the HA
Supervisor credential is not. This is one shared administrator workspace, not
per-HA-user isolation.

Configured delivery supports direct push or PR/MR. Preparation uses the destination
branch for push, or a task worktree from the configured base for PR/MR. Dirty,
divergent and unfinished work is preserved. Delivery does not silently switch
modes, force-push, merge, or reload/restart HA. These conventions guide agents;
they do not restrict arbitrary Git shell commands. Repository permissions provide
any required forge-side enforcement.

The user's separate HA Git app owns deployment. Pushing its watched branch may
deploy changes; syntax checks do not establish live HA behavior. Saved credentials,
workspaces and sessions persist in `/data`; active processes do not survive app
restart. Browser disconnects are intended to leave server-side work running.
Backups contain credentials and require controlled access and restore testing.
Storage thresholds stop the app while preserving work, rather than enforcing a
hard filesystem quota or automatically pruning user sessions.

## Deliberate scope exclusions

The following are outside current scope, not commitments for a next release:

- ARM builds and multiple configured repositories.
- Read exclusions and device/area-inherited label grants.
- Additional control adapters, script/scene execution capabilities and broader
  Supervisor/host/other-app diagnostics.
- App-owned provider/forge credential forms and forge API integrations.
- Scheduled investigations, background task/completion notifications,
  fix verification, scheduled follow-up and deployment-status integrations.
- A dedicated automation-creation skill; ordinary conversation already supports
  configuration changes and configured Git delivery.
- External agent workers and a separate HA runtime for candidate validation.

Build dependencies use separate Node, Python and CLI stages with late source and
metadata copies to preserve cache reuse. Release-version conventions live in the
[README](../README.md#development). CI cache import/export was skipped by user
preference; package-manager cache mounts remain optional optimization work, with
no implementation commitment.
