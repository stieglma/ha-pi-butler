# Pi Butler — implementation plan

Updated: 2026-11-10.
Status: requirements consolidated; implementation has not started.
Target: one self-contained Home Assistant app, amd64 only.
Technical assumptions will be validated after the first version is installed in Thomas's HA environment.

## 1. Product and scope

Pi Butler is a persistent, Git-first Home Assistant workspace powered by Pi Coding Agent and Pi Web. Users work through HA ingress, including Pi Web's interactive terminal. The app helps investigate HA issues, author configuration changes, and deliver those changes using a configured Git workflow.

Initial installation:
- HAOS VM on Proxmox; no Proxmox-specific integration.
- Core 2026.11.1, Supervisor 2026.10.5, HAOS 18.4.
- Architecture: amd64. ARM and multi-architecture builds are out of scope.
- App name: Pi Butler. Slug: `pi_butler`.

V1 includes:
- Pi and Pi Web, including the terminal, running as an unprivileged user.
- One optional configuration repository, independently cloned into app-owned storage.
- Git, OpenSSH client, GitHub CLI (`gh`), and GitLab CLI (`glab`).
- User-managed Git/PR and model-provider authentication through existing Pi/Pi Web UI or terminal.
- Persistent workspaces, authentication/configuration, saved sessions and transcripts.
- Broad HA read access through an internal access service.
- Configurable runtime control grants by entity, domain and directly assigned HA label.
- A separate permission for manually triggering automations.
- Configurable direct-push or PR/MR delivery, honoring configured branches.
- On-demand diagnostics and logs, starting with HA Core and the app itself.

Constraints:
- One app installation; no companion app or required custom HA integration.
- No manual HA auth-file edits or custom internal roles.
- No shared live HA configuration directory, host filesystem or Docker socket.
- Existing HA Git app remains responsible for synchronizing deployed configuration.
- No app-managed GitHub/GitLab API integrations or credential forms.
- Broad read access does not include exporting authentication secrets or arbitrary host files.

## 2. Architecture

```text
Browser
  → HA ingress
  → ingress adapter
  → Pi Web server + session daemon
      → Pi agent / interactive terminal
          → private Git workspace
          → gh / glab / Git / SSH
          → internal HA access service
              → Supervisor / HA APIs
```

Run the web server, session daemon, agent and terminal under the same unprivileged `pi` user so they share user-managed tooling and authentication.

Run the internal HA access service under a separate service identity. It holds the upstream HA credential and the trusted access policy. Expose its approved operations through local MCP, using a small stdio adapter over a permission-controlled Unix socket. The adapter runs as `pi` and never receives the upstream credential.

Use the automatic Supervisor credential for HA access, with `homeassistant_api: true`. Core log retrieval may additionally require `hassio_api: true` and the `homeassistant` role. Enable only the permissions needed for the implemented endpoints. Do not request `manager` or `admin` roles for v1.

Use explicit REST/WebSocket operations behind the internal service. Native HA MCP is a reference and possible later upstream interface, not a required user setup step. Its read-only mode alone cannot implement configurable writes or restrict a token used through other APIs.

Use HA-compatible process supervision for the web server, session daemon, ingress adapter and access service. Follow Pi Web's manual container run path rather than installing native user services.

### Credential boundary

The agent must not be able to read or modify the access service's credential, policy or executable code.

Implementation requirements:
- Launch Pi processes from a clean environment without Supervisor credentials.
- Protect app options, service environment files, process inspection, file descriptors and credential copies.
- Prevent the `pi` user from becoming the service/root user or altering startup services.
- Give Pi's terminal the same restrictions as the agent.
- Run with HA protection mode enabled and no host networking or hardware privileges.
- Reject unauthenticated direct access to the ingress listener from other apps.
- Do not present separate Linux users alone as proof of isolation; verify actual behavior in HA.

This boundary is intended to resist ordinary agent tools and shell commands. It is not a guarantee against kernel/container exploits or a compromised privileged access service.

## 3. Runtime access policy

### Reads

V1 reads all HA entities, states, registry metadata, history and available diagnostic data. No entity/domain/label read restrictions are required.

Use bounded/paginated queries, log redaction and explicit truncation notices. These operational limits do not change the broad entity read policy.

### Writes

Default: deny all runtime writes until the user grants access in app configuration.

Grant normal control operations together. A light control grant includes on/off/toggle and supported ordinary light controls; users do not select every service individually. Maintain an explicit supported-operation catalog so unknown or global administrative actions cannot slip through.

Initial operation adapters:
- Lights: on/off/toggle and supported light parameters.
- Switches and input booleans: on/off/toggle.
- Calendars: supported event mutation operations, documented per installed integration.
- Automations: explicit manual trigger capability; enable/disable handled as normal control only when separately granted.
- Add other domains through the same adapter/capability interface. Unsupported operations return a clear error rather than generic API forwarding.

This initial catalog is an implementation baseline, not a claim that all calendar integrations support the same mutations.

Example logical policy:

```yaml
ha_access:
  write:
    enabled: true
    allow:
      - capability: control
        match:
          entity_ids: [calendar.family]
      - capability: control
        match:
          domains: [light]
          label_ids: [pi_butler_writable]
      - capability: trigger_automation
        match:
          entity_ids: [automation.evening_routine]
    deny:
      entity_ids: [light.nursery]
```

Translate this logical structure into the actual HA options schema during implementation.

Policy semantics:
- Allow rules combine with OR.
- Selector categories within one rule combine with AND; values within a category combine with OR.
- Explicit exclusions override grants.
- Labels mean labels directly attached to entities in v1; store label IDs.
- Resolve membership from current registry data and fail closed if resolution is unavailable.
- New entities matching an allowed domain/label inherit access. Removed membership revokes access on subsequent requests.
- Resolve supported multi-target selectors to explicit entities before calling HA. Reject missing/ambiguous targets and any request containing a denied target; do not execute a silent partial subset.
- Validate entity references in action data as well as target fields.
- Global service/configuration calls and arbitrary URL/template/event forwarding are excluded.
- Ordinary control rights never imply permission to trigger automations.
- Indirect effects of authorized actions are accepted. Existing automations may react to changes; manually triggered automations may affect other entities.
- Script/scene execution is deferred until explicit execution capabilities are implemented.
- Policy remains writable only through trusted app configuration. Expose the effective policy and matched entities through a read-only summary.

Record action, resolved targets, decision and policy version for diagnosis; avoid storing sensitive payloads. Assess registry-change races during integration validation.

## 4. Git and delivery

### Repository configuration

The repository is optional. Keep Pi Web, terminal and HA access usable without one or while authentication is pending.

Configure:
- Repository URL: SSH or HTTPS, including self-hosted services/custom ports.
- Checkout branch.
- Git author name/email, distinct from login identity.
- Delivery mode: `push` or `pull_request`.
- Push mode: destination branch.
- PR mode: target/base branch and work-branch prefix.

Support ordinary user-managed SSH configuration and keys. Optional app-managed SSH credential fields are a convenience, not a v1 prerequisite; omit them from the initial UI unless needed.

Do not require a separate Git credential setup when CLI authentication already supplies it. Preserve the repository's configured transport.

### Authentication and onboarding

Bundle gh and glab. Users authenticate in the Pi Web terminal under the `pi` user.

Examples:
- GitHub HTTPS: `gh auth login --git-protocol https`, then `gh auth setup-git`.
- GitLab HTTPS: `glab auth login --git-protocol https --setup-git-credential-helper`.
- SSH: configure an authorized key and known hosts in the persistent user home. CLI API authentication alone does not authenticate SSH.

Validate commands against bundled CLI versions. Document browser/device login for a headless container; do not assume the container can open the user's browser or access a desktop keychain.

Startup must reach the UI before authentication is complete. Report repository setup as pending and provide a retry path after terminal login.

PR mode help must state that the selected forge tooling must be authenticated with repository permissions. No app API-token fields or OAuth integrations.

Git/forge credentials are intentionally usable by the Pi user and are separate from the inaccessible HA credential. Delivery settings guide the workflow; they are not a security boundary against arbitrary Git shell commands. Use server-side repository permissions/branch protection where stricter enforcement is desired.

### Delivery behavior

When the user asks the agent to deliver, follow the configured mode:
- Push: commit and push to the configured destination branch.
- PR/MR: push a work branch, then use the authenticated CLI to create/update a PR/MR against the configured base.

Do not silently substitute direct push when PR authentication or tooling fails. Report the setup problem and preserve the work.

Honor configured branches; no hardcoded main branch. Verify PR/MR target and report the resulting URL or pushed commit. Do not merge PRs or restart/reload HA as an implicit delivery step.

Preserve dirty/divergent work and report conflicts. No automatic reset or force-push.
Before edits, inspect `butler-workspace settings` and use `prepare NAME`: push mode
works directly on the configured destination branch, while PR mode creates an
isolated task worktree from the configured base. Do not create a task branch by
default in push mode. Concurrent tasks must defer or explicitly arrange isolation.

Run local syntax/configuration checks appropriate to changed files and report failures before delivery. A local YAML check is not a complete HA validation, and a live check validates deployed configuration rather than an unmerged candidate.

The external HA Git app owns deployment. Pi Butler has no dependency on that app's identity/API; document which branch it should watch. A push to its watched branch may cause deployment.

## 5. Persistence and operations

Suggested paths:

| Path | Ownership/purpose |
| --- | --- |
| `/data/home/` | Pi user's home: Git config, SSH keys, gh/glab config |
| `/data/workspaces/` | Repository clones and worktrees |
| `/data/pi/` | Pi authentication, models, settings and saved sessions |
| `/data/pi-web/` | Pi Web state/configuration |
| `/data/diagnostics/` | Bounded investigation artifacts |
| `/data/service/` | Restricted HA access-service state; not readable by Pi |

Set HOME/XDG/Pi/Pi Web paths explicitly and apply ownership on initialization. Keep reproducible application binaries in the image.

Persist login/configuration across app updates and container replacement. Saved sessions survive restarts; active processes do not. Browser disconnects should leave active server-side work running.

Configure model providers using existing Pi/Pi Web flows; avoid a parallel app-owned provider configuration UI.

Collect logs on demand, initially from Core and Pi Butler. Retrieve HA logs through APIs, not shared folders. Additional app/Supervisor/host log sources are follow-up work if they need broader privileges.

Bound line counts, bytes, query duration and retention. Include timestamps and source/truncation metadata. Treat diagnostic text as untrusted input.

Bound concurrency and transcript/artifact growth. Document backup inclusion for the persistent home, credentials, workspaces and saved sessions; exclude reproducible caches where supported. Exercise update/restore behavior in HA validation.

## 6. Repository layout and deliverables

Keep this repository structured as an HA app repository:

```text
PLAN.md
README.md
repository.yaml
pi_butler/
  config.yaml
  build.yaml                 # if required by selected build workflow
  Dockerfile
  DOCS.md
  CHANGELOG.md
  apparmor.txt               # if a custom profile is needed
  rootfs/                    # service definitions, startup, ingress configuration
  src/
    ha-access/               # credential holder, policy evaluation, HA adapters
    mcp-client/              # stdio-to-local-service adapter
    workspace/               # repository initialization/delivery configuration
  tests/                     # meaningful policy and boundary tests
```

Choose the HA-compatible base image/process supervisor and Node runtime during implementation. Account for Pi Web's native PTY dependency on amd64. Pin a compatible Pi/Pi Web pair, CLI binaries and base image; record the selected versions.

Research observed Pi 1.5.1 and Pi Web 1.202611.1 source metadata. Treat these as candidates, not a tested version lock. Inspect the published Pi Web artifact's SDK bundling to avoid conflicting CLI/SDK versions.

Prefer reusing Pi Web's UI, terminal, provider login and diff/session functionality. Add only app-specific configuration/status and HA tools.

## 7. Implementation milestones

### Milestone 1 — Build the first installable app

- Add repository/app metadata, Dockerfile and amd64 build configuration.
- Install Pi/Pi Web, Git, SSH, gh and glab.
- Add process supervision, ingress routing and persistent user/state paths.
- Start the UI and terminal even when repository/provider authentication is incomplete.
- Document local repository installation into HA.

Deliverable: an installable app with Pi Web reachable through HA ingress.

### Milestone 2 — Complete first-version functionality

- Implement the internal HA access service, credential separation and MCP adapter.
- Add broad read tools and the policy evaluator with initial control adapters.
- Add configurable entity/domain/direct-label grants and automation-trigger rights.
- Add optional repository setup, retry behavior and worktree handling.
- Supply push/PR workflow guidance driven by app configuration.
- Add on-demand Core/app diagnostics, access summary and setup status.
- Document terminal-based provider/Git login and credential persistence.

Deliverable: first functional version ready for installation and real HA integration testing.

### Milestone 3 — Validate inside Thomas's HA environment

Validate technical assumptions only once the first version is integrated into HA. Do not require a separate preimplementation compatibility spike.

Check:
- Ingress prefix handling, static assets, terminal PTY and WebSockets.
- Browser reconnects and continued agent sessions after disconnect.
- Non-root operation under HA protection mode.
- Supervisor API connectivity, registry/history access and actual log coverage.
- Credential isolation from terminal/agent environment, files and process access.
- Direct denied HA actions and attempts to bypass the policy.
- Label resolution, explicit exclusions, mixed targets and automation rights.
- GitHub/GitLab login, SSH/HTTPS Git, push and correctly targeted PR/MR workflows.
- Saved state/credentials across restart, update and container replacement.

Use meaningful local policy/schema checks during implementation; integration behavior remains unverified until this milestone. Record failures and limitations explicitly. If a boundary fails, fix it within the single-app constraint; do not silently introduce a companion app or relax the authority model.

Deliverable: tested first version with documented findings and necessary fixes.

### Milestone 4 — Stabilize and document

- Resolve issues found in HA.
- Verify backups/restores and dirty/divergent workspace recovery.
- Finalize supported-operation catalog and setup/troubleshooting documentation.
- Record known limitations and release an amd64 version.

## 8. Acceptance criteria

The first version is considered validated when:
- One amd64 HA app provides Pi Web and terminal through authenticated ingress.
- No shared live HA filesystem, companion app or manual auth storage edits are needed.
- Agent/terminal processes cannot retrieve the HA credential or edit their access policy.
- Broad reads work; writes default to denied.
- Entity/domain/direct-label grants and exclusions govern supported direct control actions.
- Light on/off/toggle share a control grant.
- Automation triggering requires its distinct grant; downstream effects are accepted.
- Unknown actions and ambiguous/mixed denied targets cannot bypass authorization.
- No repository/login is required to reach the UI and terminal.
- gh/glab authentication can supply both Git and PR/MR access without duplicate credentials.
- Both delivery modes honor configured branches and preserve work on failure.
- Credentials, repository work and saved sessions persist across replacement.
- Core/app diagnostics are available on demand with bounded output.
- Provider setup uses existing Pi/Pi Web flows.
- Integration results and remaining limits are documented.

## 9. Deferred features

- ARM builds.
- Read exclusions by entity/domain/label.
- Labels inherited from devices/areas.
- Additional control adapters and explicit script/scene execution capabilities.
- App-owned password credential UI or forge API integrations.
- Additional app/Supervisor/host log sources requiring broader access.
- Multiple configured repositories.
- Scheduled investigations, notifications and deployment-status integrations.
- Full candidate-configuration validation against a separate HA runtime.
- External agent workers.

No further product decisions block starting the first version. Implementation details should be resolved using this plan; ask only when evidence reveals a material tradeoff that changes the agreed behavior.

## 10. Research references

These support the design; they are not evidence of a successful installation.

- [Pi MCP configuration](https://raw.githubusercontent.com/earendil-works/pi/main/packages/coding-agent/docs/mcp.md)
- [Pi package metadata](https://raw.githubusercontent.com/earendil-works/pi/main/packages/coding-agent/package.json)
- [Pi Web package metadata](https://raw.githubusercontent.com/jmfederico/pi-web/main/package.json)
- [Pi Web installation/container operation](https://pi-web.dev/install)
- [Pi Web configuration and terminal](https://pi-web.dev/config)
- [HA app configuration](https://contributors.home-assistant.io/apps/reference/configuration/)
- [HA ingress](https://contributors.home-assistant.io/apps/guides/ingress/)
- [HA/Supervisor communication and credential authority](https://contributors.home-assistant.io/apps/guides/communication/)
- [Supervisor roles](https://contributors.home-assistant.io/apps/supervisor-api/)
- [Core log endpoints](https://contributors.home-assistant.io/apps/supervisor-api/core/)
- [HA MCP integration](https://www.home-assistant.io/integrations/mcp_server/)
- [Core 2026.11.1 MCP implementation](https://raw.githubusercontent.com/home-assistant/core/2026.11.1/homeassistant/components/mcp_server/server.py)
- [Core 2026.11.1 service target handling](https://raw.githubusercontent.com/home-assistant/core/2026.11.1/homeassistant/helpers/service.py)
- [HA action behavior](https://www.home-assistant.io/docs/automation/action/)
- [Git SSH/HTTPS transport](https://git-scm.com/docs/git-clone)
- [GitHub CLI login](https://cli.github.com/manual/gh_auth_login)
- [GitHub CLI Git credential helper](https://cli.github.com/manual/gh_auth_setup-git)
- [GitLab CLI login and credential helper](https://docs.gitlab.com/cli/auth/login/)
