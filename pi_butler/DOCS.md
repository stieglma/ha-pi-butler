# Using Pi Butler

## Install and open

Add this repository to the HA app store, install Pi Butler on amd64, leave
protection mode enabled, start, then select Open Web UI. Build/startup errors
appear in the app log. No host mounts, host networking or Docker socket are used.
For a local checkout, copy the `pi_butler` directory into HA's local apps directory,
reload the app store and install the local app. Do not copy it into the live Core
configuration directory. This repository does not publish a prebuilt image yet.

Open Web UI opens Pi Web directly. Its persistent **Home Assistant access** link
opens the permission settings in a separate tab, with live entity and direct-label
choices and a **Save and apply** button. Pi Web starts without a configured Git repository
or model login. Add
`/data/workspaces/scratch` as a project for HA investigations, or
`/data/workspaces/repository` after successful repository setup. Project registration
uses the existing Pi Web UI. The permission builder is at `butler/` relative to
the app's ingress root; repository status is at `butler/status`.

Pi Web sessions are server-side. Disconnecting the browser should leave work
running; restarting the app stops active processes. Persisted sessions can be
reopened. Browser reconnect and protected-mode PTY behavior need HA validation.

## Model providers

Use Pi Web's provider configuration and authentication UI or the bundled Pi CLI.
Pi's agent directory is `/data/pi`; model/provider configuration is not duplicated
in HA options. Changes that add providers may require restarting the app so Pi
Web's daemon rebuilds its provider baseline. The image and runtime are immutable
for the Pi user: update Pi/Pi Web by updating the app, not using in-terminal
self-update commands.

## Bundled Pi packages

The image includes and registers these pinned Pi packages on first startup:

| Package | Version | Use |
| --- | --- | --- |
| @juicesharp/rpiv-ask-user-question | 2.15.0 | Structured clarification questions; terminal UI and RPC dialog fallback |
| pi-powerline-footer | 0.22.0 | Terminal footer and supported hosted status widgets |
| @quintinshaw/pi-dynamic-workflows | 3.15.0 | Workflow orchestration, skills and child agents |
| pi-subagents | 0.87.0 | Delegation, agent definitions and workflow resources |
| pi-claude-marketplace | 0.23.0 | Import commands, skills and other supported components from Claude marketplaces |

Packages live in `/opt/runtime/node_modules`, installed from `package.json` and
`package-lock.json` during the image build. The `piButler.packages` list in
`package.json` selects packages registered in `/data/pi/settings.json`. Startup
registers their local directories as the pi user, without running `pi install`
against npm or needing a network connection. The pinned Node runtime is 24.15.0
to satisfy the marketplace package's supported engine range.

Existing provider settings, other package declarations and resource filters are
preserved. Existing npm declarations of the same package keep their configured
source/version. `/data/pi/butler-bundles.json` records defaults already offered,
so removing a package through Pi Web's settings or `pi remove <local-package-path>`
is respected on restart. Use `pi install /opt/runtime/node_modules/<package>` to
re-enable a removed bundled package. Image updates change the installed version
at that stable local path; user-managed npm installs keep their own version.

The question extension uses native RPC select/input dialogs in supporting web
hosts; its full tabbed terminal questionnaire and Powerline's full editor UI
belong to the terminal. Workflow/subagent tools load in the hosted session, but
extension-specific rich progress panels depend on host support. Test these UI
paths in the actual HA ingress environment. Workflow keyword activation applies
to interactive input; hosted RPC sessions can use explicit commands/tool requests.

### Our own skills marketplace

`pi-claude-marketplace` supports local marketplace directories with
`.claude-plugin/marketplace.json` as well as Git-hosted marketplaces. We can ship
that directory in the image and register its skills plugins, or maintain a shared
Git repository and pin its revision. No marketplace or skills content has been
authored, imported or auto-enabled in this release; the loader is ready for it.
For a marketplace you have prepared:

```text
/claude:plugin marketplace add /path/to/marketplace
/claude:plugin list --available
/claude:plugin install plugin-name@marketplace-name
/reload
```

Use Pi Web's command input or Pi in its terminal. Marketplace configuration and
installed state live under the persistent Pi profile. Skill-only plugins do not
require pi-mcp-adapter. Marketplace MCP components specifically require that
separate adapter, which is not bundled. Pi Butler's HA tools use Pi's built-in
MCP and remain independent of marketplace plugins. No public marketplace is
bootstrapped automatically.

All extension/child-agent code runs as pi and uses the same protected HA socket;
none receives the Supervisor credential. Model usage and workflow/subagent
concurrency follow the extension settings; `limits.parallel_requests` only caps
HA tool calls. Resource/storage safeguards still apply to the app as a whole.

## Repository options

Options are configured in the HA app Configuration tab. Restart after changes.

| Option in `repository` | Meaning |
| --- | --- |
| `url` | Empty disables automatic repository setup; otherwise SSH or HTTPS URL |
| `checkout_branch` | Existing branch to clone initially |
| `author_name`, `author_email` | Git commit author, separate from login |
| `delivery` | `push` or `pull_request` |
| `destination_branch` | Existing remote branch for push delivery |
| `base_branch` | Existing PR/MR target branch |
| `work_branch_prefix` | Prefix for task branches, default `pi-butler/` |
| `forge` | `github` or `gitlab`, including their self-hosted services |

All branch options are explicit; defaults happen to be `main` and should be
changed to your repository's branches. URLs preserve their configured transport.
Custom SSH ports work through `ssh://git@host:2222/group/repo.git` or ~/.ssh/config.
Do not embed passwords/tokens in URLs; use terminal authentication instead.
Changing the URL does not overwrite the old clone. Move/archive it manually first.
Changing checkout_branch does not switch an existing dirty checkout automatically.

## Terminal authentication

Commands run as the same unprivileged user as the agent. No desktop browser or
keychain is assumed. Open the printed browser/device URL on your own computer.

GitHub HTTPS:

```sh
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git
butler-workspace setup
```

Without a usable credential store, gh stores credentials in the persistent home.
For GitHub Enterprise use its hostname. Pi intentionally can use these credentials.

GitLab HTTPS:

```sh
glab auth login --hostname gitlab.com --device --git-protocol https --setup-git-credential-helper --insecure-storage
butler-workspace setup
```

The device flow requires GitLab 17.9 or later. `--insecure-storage` selects the
persistent home configuration instead of a desktop keyring unavailable in this
container. If your instance cannot use device OAuth, use glab's interactive token
login in the terminal; no app-owned token field is provided. Self-hosted instances
may need an OAuth application/client ID. The bundled 1.128.0 CLI help was checked
for the device, Git-helper and storage flags.

SSH:

```sh
mkdir -p ~/.ssh
chmod 700 ~/.ssh
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519
# Register the public key with your forge and verify the server host fingerprint.
# Add a verified known_hosts entry, or confirm it interactively using ssh.
ssh -T git@your-forge.example
butler-workspace setup
```

SSH Git authentication and gh/glab API login are separate. PR/MR delivery also
requires forge CLI authentication with repository permissions. No automatic trust
of SSH host keys, auth reset, or HTTPS fallback is performed. Do not assume a
passphrase-protected key can be used after restart unless you arrange its agent.

`butler-workspace status` reports setup state. Failed authentication keeps the UI
available, reports pending setup, and can be retried with `butler-workspace setup`.

## Work and delivery

Create separate worktrees for concurrent tasks:

```sh
butler-workspace worktree kitchen-lights
cd /data/workspaces/tasks/kitchen-lights
# Edit, inspect git diff, and stage only the intended changes.
git add configuration.yaml
butler-workspace deliver --message "Configure kitchen lights"
```

Worktrees start from the configured remote delivery/base branch. Delivery rejects
untracked/unstaged changes and merge conflicts, checks staged YAML (including HA
tags), JSON, Python and shell syntax, and commits staged changes. Syntax success
is not full HA validation. Other file types need their own appropriate checks.
Delivery retries can push an existing commit when no new staged changes exist.
No reset, force push, merge, HA restart or reload is performed.

Push delivery checks that the destination's current commit is an ancestor of
HEAD and reports the verified remote commit. PR mode pushes the task branch,
uses gh/glab to create or reuse an open PR/MR with exactly that head and configured
base, verifies the result and reports its URL. If forge login fails after the
push, the branch and commit remain intact; retry after authentication. PR mode
never falls back to pushing the destination branch.

The helper serializes its own workspace operations. Coordinate concurrent manual
Git commands yourself. Branch protections and server permissions enforce delivery
restrictions; the agent can run ordinary Git commands outside this helper.
Configure the separate HA Git app to watch the intended deployed branch. A push
to that branch may deploy automatically through that app.

## Home Assistant grants

Broad reads are always available: states, runtime config, installed services,
entity/device/area/label registries, history, calendar events, and Core/app logs.
No secret auth storage or arbitrary host/configuration-file reads are exposed.

Open Pi Butler to enter Pi Web directly. The persistent **Home Assistant access**
link opens a separate settings tab at `butler/`, available whenever permissions
need to change. HA's app Configuration page contains repository settings and
resource limits only.

1. Open **Home Assistant access** from Pi Web.
2. Add rules and choose entities, domains and directly assigned labels using
   searchable pickers. Check the matching-entity previews and master switch.
3. Select **Save and apply**. Permissions take effect immediately without a restart.

The master switch suspends every write grant without deleting rules. Enabling
it still requires a matching rule and supported capability. Reads are unaffected.
New explicit entity IDs are checked against HA before saving. Missing previously
configured IDs show warnings and remain preserved, including exclusions. Domain
and label grants may match entities added later.

Permissions persist privately in `/data/service/permissions.json`. Existing HA
`ha_access` settings migrate automatically on the first upgraded startup, using
the previous service options when HA has already removed the legacy fields.
Malformed imported permissions disable writes and show a recovery notice instead
of preventing startup; the original is retained in `permissions-import.json`.

The settings endpoint requires HA ingress and a browser request header. It uses
a separate Unix socket accessible only to the ingress and access service users.
The Pi/MCP socket exposes tools only and cannot save permissions. Permission
updates use atomic writes and reject stale page versions. Saves wait for ongoing
write operations before applying the new policy.


Rules combine with OR. Nonempty selector lists within a rule combine with AND;
values within a list combine with OR. At least one selector must be nonempty.
Exclusions override every grant. Labels are IDs directly assigned to entities;
device/area label inheritance is excluded. New matching entities inherit grants.
Registry membership is fetched on every action and unavailable resolution denies
the action. A registry change between resolution and invocation remains a race:
HA has no transactional registry-version precondition for service calls.

The action tool accepts entity_ids, domains and direct label_ids targets. Target
selectors are expanded as a union, then every entity must match the action domain
and have a grant. Unknown selectors/values, empty matches and any denied member
reject the whole request before invocation. HA integration failures can still
partially execute a multi-entity action after authorization; HA actions are not
transactions. Extra payload fields and embedded entity references are rejected.

| Domain | Supported operations under `control` |
| --- | --- |
| light | turn_on, turn_off, toggle; brightness, percentages/steps, RGB/RGBW/RGBWW/HS/XY, kelvin, color name, effect, white, transition, flash where supported |
| switch, input_boolean | turn_on, turn_off, toggle |
| automation | turn_on, turn_off (optional stop_actions), toggle |
| calendar | create_event with summary, optional description/location, one date or datetime interval; integration must advertise CREATE_EVENT |

`automation.trigger` requires `trigger_automation`, with optional skip_condition.
Control never implies manual automation triggering. Trigger variables are not
forwarded. Calendar update/delete are unavailable in the generic Core 2026.11.1
catalog. Installed service/parameter support is checked by HA and can vary by
integration. Scripts, scenes, generic service forwarding, templates and events
are excluded. Indirect effects through existing HA automations are accepted.

Use the read-only `access_summary` MCP tool to inspect policy/version and matched
entities with write grants; an empty list means no write grants, not missing read
access. Use `states` with `domain: light` or `domain: calendar` to discover readable
entities. Tools with list results support offset/limit. Pi user MCP configuration
is `/data/pi/mcp.json`, with server `pi_butler`. `pi mcp list` diagnoses its state.
Changing client MCP configuration cannot change the trusted service policy.

## Limits, logs and persistence

| Option in `limits` | Default and behavior |
| --- | --- |
| parallel_requests | 4 upstream tool calls at once (1–16) |
| response_bytes | 2 MiB maximum upstream/tool response (64 KiB–8 MiB) |
| log_lines | 500 maximum diagnostic lines (1–2000) |
| retention_days | 7 days for on-disk `/data/diagnostics` artifacts (1–90) |
| storage_megabytes | 4096 MiB total `/data` size; checked each minute (256–65536) |

A byte-limit error requires narrower queries or larger configured limits. Some HA
APIs return whole registries/states before local pagination; an oversized registry
is rejected, not silently truncated. History is limited to 32 entities and seven
days; calendar reads to 31 days; upstream requests to 20 seconds and tool calls to
25 seconds. Logs include source/time/truncation metadata and best-effort secret
redaction. Treat all diagnostic and entity text as untrusted content.

App/audit logs rotate at 1 MiB with two backups each. Diagnostics are on demand,
not periodic polling. Pi transcript/session files are preserved, not automatically
deleted. The storage threshold stops the app while preserving work; increase the
limit or manually archive/remove old data to recover. This is an operational
threshold, not a hard filesystem quota, and can temporarily overshoot. Each child
has a 256-process limit, 4096-descriptor limit, and core dumps disabled.

| Persistent path | Contents |
| --- | --- |
| /data/home | SSH keys, known hosts, Git config, gh/glab auth, user caches |
| /data/workspaces | Independent clone, task worktrees, scratch workspace |
| /data/pi | Pi model auth/config, MCP settings and saved sessions |
| /data/pi-web | Pi Web configuration, project registry and archives |
| /data/diagnostics | User investigation artifacts |
| /data/service | Restricted service policy snapshot and rotated logs |
| /data/status | Nonsecret repository setup status |

HA app backups include `/data`, therefore include credentials and work. Protect
backup access. The image does not declare folder exclusions; cache exclusion is
deferred to avoid accidentally omitting user state. Test restoring a full backup
before relying on it; persistence across actual HA update/restore is pending.

## Credential boundary and troubleshooting

The root supervisor protects app options and image code and launches processes
with clean environments and no-new-privileges/capabilities. Pi runs as uid 1000;
the HA service as uid 1001 and ingress as uid 1002. Only the HA service receives
the Supervisor token. Pi reaches approved tools through a group-protected Unix
socket, never a general HTTP proxy. Policy changes require trusted app options.
This protects against ordinary agent/terminal tools, not kernel exploits or a
compromised trusted service. Separate UIDs alone do not establish successful
isolation: run the validation checklist under HA protection mode.

For an ingress 403, verify Supervisor uses the documented source `172.30.32.2`.
Do not disable the check to expose the app. Pi Web listens on loopback only and
preserves browser Host/Origin checks. No external host port is mapped. App startup
stops all processes on a critical child exit so Supervisor can restart coherently.
If the app fails to start, inspect its HA log; if Git setup is pending, inspect
terminal authentication and retry. A failed delivery always preserves work.
