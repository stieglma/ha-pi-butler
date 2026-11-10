# Pi Butler implementation plan

Date: 2026-11-10. Source requirements: `PLAN.md`.

## Decisions and scope

Implement milestones 1 and 2 in this repository, with automated local validation.
Milestones 3 and 4 require Thomas's amd64 HAOS installation; record their checks
and outcomes separately rather than claiming a successful installation locally.
No product questions remain: section 9 of PLAN.md explicitly settles scope.

Use Pi 1.5.1 and Pi Web 1.202611.1 (published packages verified), Node 24 on
Debian bookworm for the native PTY, Python 3 with aiohttp for the isolated service,
MCP bridge, ingress adapter, and PID 1 supervisor. Pi Web resolves its existing
Pi SDK; install both into one global npm tree and assert SDK resolution at build.
Pin the base digest and package dependency lock, and pin/checksum forge binaries.
Do not invoke Pi Web's native user-service installer inside the container.

## Implementation sequence

1. Add HA repository metadata, amd64 app config and build instructions. Enable
   ingress only, Core API and Supervisor homeassistant role for Core logs; no
   shared folders, host networking, Docker socket or hardware privileges.
2. Add a minimal PID 1 supervisor: initialize persistent paths, protect options
   and service storage, create a clean environment per child, launch each child
   in a separate process group, reap children, terminate all children on shutdown
   or critical service exit. Run Pi services as uid 1000; access service as uid
   1001; ingress as uid 1002. Apply no-new-privileges and remove supplementary
   groups. Keep credentials exclusively in the access process environment.
3. Store trusted policy in service-only storage and create a Unix socket in a
   root-owned directory with a shared client group. Root-owned immutable image
   code and startup files must not be writable by pi. No sudo or setuid binaries.
   Protect /data itself against renaming options or service paths. Disable core
   dumps. Verify process/file/socket behavior with an HA boundary script.
   Run artifact expiration as pi, never as root over user-controlled paths.
4. Proxy HTTP and WebSockets from ingress to loopback Pi Web. Check the actual
   peer IP against HA's documented ingress source, never a forwarded header.
   Preserve Host and Origin; support Pi Web's deployment-independent nested URLs.
   Serve small app-specific setup/status endpoints under /butler/. Bind no
   additional external ports. Pi Web and sessiond run manually with explicit
   persistent config, session, home and Unix-socket paths.
5. Implement a bounded authenticated upstream client with fixed REST routes and
   fixed WebSocket command names. Read states, config, services, entity/device/
   area/label registries, history, calendar events and Core/app diagnostics.
   No arbitrary API forwarding, templates, events or secret configuration files.
   Time out requests, bound responses and tool concurrency; paginate list tools,
   mark truncation, redact secret fields and known token values.
6. Implement policy matching with OR across rules, AND across nonempty selector
   categories and exclusions first. Refresh states/registry for each action;
   require complete registry resolution. Resolve entity/domain/direct-label
   selectors to explicit entities; reject any empty, unknown or denied target.
   Require a separate trigger_automation capability. Whitelist each operation's
   data fields and reject extra fields (including embedded entity selectors).
   Calendar v1 supports create_event only: Core 2026.11.1 exposes no generic
   update/delete action. Check installed service availability and feature flag.
   Audit decision, targets and policy hash without payloads, with rotation.
7. Expose tools through newline-delimited MCP JSON-RPC on stdio, bridged to the
   private Unix socket. Implement initialize, ping, tools/list, tools/call and
   notification handling, bounded framing, protocol errors and stdout discipline.
   Install user-level MCP configuration without overwriting existing servers.
8. Supply a Pi-user workspace CLI: optional clone, pending status/retry, Git author,
   safe worktrees and explicit push/PR delivery. Read root-owned delivery defaults;
   preserve dirty/divergent work, never reset/force-push. Require explicit commit
   message and branch, run syntax checks, verify upstream branches and PR/MR base,
   use gh/glab for forge operations and report URL/commit. Do not deploy/reload HA.
9. Document installation, option schema, terminal logins, operations, backup paths,
   quotas, versions, validation limits and release notes. Add CI unit tests and an
   amd64 Docker build. Add policy, MCP, upstream and Git failure-path tests using
   fake upstreams/temporary repositories, without needing HA credentials.

## Configuration representation

HA options contain `repository` (URL, checkout, author, delivery, destination,
base, prefix and forge), `ha_access` (enabled, allow list of capability + lists of
entity_ids/domains/label_ids, denied entity IDs), and `limits` (parallel requests,
response bytes, diagnostics lines and retention). Empty allow selectors are
invalid, write defaults to false, no token/provider fields are added.
Configuration changes require an app restart. Effective policy is read-only.

## Validation and acceptance

Run Python tests, compile sources, parse HA YAML, inspect shell scripts, exercise
MCP over stdio and local Git setup/delivery against disposable bare remotes.
Docker is unavailable in this workspace: image/native PTY validation must run in
CI or HA. Live HA tests cover ingress/assets/WebSockets, protected process and
file access, Supervisor authority/log endpoints, registry churn, mixed targets,
provider/forge authentication, browser reconnect, persistence and restore.
Record actual results in VALIDATION.md. Never mark live acceptance criteria as
passed based solely on mocks. Fix integration failures before calling v1 validated.

## Known tradeoffs to assess during integration

Registry checks and service invocation are separate HA API operations; resolve
immediately before writes, but HA offers no atomic registry-version precondition.
Bounded API reads may reject oversized upstream responses rather than exhaust
memory. Diagnostic redaction is best effort; diagnostics remain untrusted text.
Pi-user quotas are operational safeguards, not a hostile-user filesystem quota.
Trusted HA administrators can change app options and therefore policy.

## Implementation status

Milestones 1–2 are implemented in the repository. Local validation and remaining
integration work are recorded in VALIDATION.md. Artifact retention runs as an
additional pi-user maintenance child; the four primary architectural services
remain ingress, web, session daemon and access. The process supervisor uses
util-linux setpriv/prlimit rather than S6, with PID 1 signal handling and reaping.
Milestones 3–4 remain pending Docker/HA execution, deployment-specific fixes and
backup/restore evidence. No live installation or validated release is claimed.

Python dependencies use a non-packaged uv project in `pi_butler/pyproject.toml`
and the committed `uv.lock`. Docker and CI run locked sync; runtime processes
continue to use `/opt/venv` directly. uv 0.11.28 is pinned in CI and by image digest
in Docker. Source modules retain their existing PYTHONPATH-based deployment.

## Bundled extension implementation

The four requested Pi extensions plus pi-claude-marketplace are pinned in the
npm manifest/lock. piButler.packages is the image-default registration list.
A pi-user profile initialization step runs before web/sessiond and merges local
package paths without replacing provider settings or resource filters. A history
file remembers defaults offered so user removal persists; new image defaults
are seeded once. Node 24.15.0 satisfies the marketplace engine requirement.
The extension loader is bundled; actual custom marketplace/skill content remains
to be defined. Native HA MCP remains separate from optional marketplace MCP.

## Permission configuration UX (0.1.3)

HA app options support static lists, not dynamic entity/label selectors. Native
fields receive English/German labels/descriptions and a supported-domain dropdown.
The ingress entry is a read-only permission builder that fetches a bounded live
catalog via the protected service socket, selects entities/direct labels, previews
rules and exports ha_access YAML. Users save it in HA app options and restart;
no HTTP/MCP operation can change policy. Ingress joins the socket client group
but still receives no upstream credential and cannot read service storage.
