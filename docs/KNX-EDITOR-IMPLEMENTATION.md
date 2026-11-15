# KNX Editor: first HA acceptance build

Prepared release: `1.1.0-beta.1`. This is an implementation candidate, not a
validated HA release. The project file from the handoff has not been imported,
changed or copied into this repository. No bus connection or programming was run.

## Included

Set `knx.enabled: true` in the app options and restart Pi Butler. An administrator
then sees **KNX Editor** in the existing Butler menu. The complete upstream UI
opens under `butler/knx/`, with HTTP, uploads, downloads and WebSockets routed
through ingress. `knx.read_enabled` controls assistant project reads; it defaults
to true. Six finite project-reading tools are automatically registered as
`pi_butler_knx`. Writes, deletion, bus access and programming are unavailable to
the assistant in this version; there is no UI for granting those rights yet.

The editor runs continuously, including without a browser. It starts with
`--no-connect` to prevent automatic bus connection; this does not disable
intentional bus actions in the privileged admin UI. Disabling the module requires
an app restart, removes its MCP registration and menu, and retains private data.
Settings and native projects persist below `/data/knx`. The upstream UI selects
the open project; reopening the previous active project is not promised yet.

The app uses cold HA backups so its SQLite state is captured with processes
stopped. This briefly stops the entire app during an HA backup, even with KNX
disabled. It does not provide project-level version history.

## Implemented trust boundaries

- Editor and read gateway run as uid 1003, without Supervisor credentials or
  supplementary Pi groups. Private project/catalog/config folders are inaccessible
  to Pi uid 1000. Editor dependencies use a separate Python 3.13 environment.
- Only ingress uid 1002 can read the web proxy credential. Every editor ASGI HTTP
  and WebSocket route requires it, even on loopback. It is never sent to browsers.
  The host-link/login routes are not proxied. Browser credentials are stripped and
  upstream cookies are neither stored nor forwarded.
- After verifying the real ingress peer, Pi Butler resolves the Supervisor-supplied
  `X-Remote-User-Id` using HA `config/auth/list` via the protected access service.
  Only active owners/admin-group members pass. Missing identity, denied lookup or
  unavailable HA fails closed. No user list or generic HA API is exposed to Pi.
- Internal editor MCP requires a random token, also when the admin changes MCP
  settings. The read gateway owns that credential and validates fixed tool names
  and argument shapes. Upstream tools added in later releases gain no access.
  The gateway socket has no settings, file-import or arbitrary-dispatch routes.
- Read audit records are private and rotated. They identify the shared assistant,
  not an individual HA user. Full admin UI mutation auditing is still pending.

The current source depends on specific upstream Python APIs. The upstream commit,
archive checksum and dependency lock are pinned; upgrades require rerunning these
boundary checks. The launcher adapters live in `butler/knx_editor.py`.

Identity references: [HA ingress identity headers](https://contributors.home-assistant.io/apps/guides/ingress/)
and [HA user-list implementation](https://github.com/home-assistant/core/blob/dev/homeassistant/components/config/auth.py).
The existing `homeassistant` Supervisor role and protection mode are retained.
The actual target Supervisor must supply the identity header; a missing header
intentionally denies KNX access instead of falling back to ingress alone.

## Repo, checkpoints and recovery design for the next increment

The agent-owned repository is an exchange/delivery destination, never the live
editor workspace. This release does not automatically open repo files. For the
first HA test, upload a **copy** through the admin UI and save a native `.xknx`
inside the editor's file folder. Download exports manually.

The next increment should use the upstream UI-thread backup service to produce a
consistent native backup and export from the same locked project revision. A
checkpoint is successful only after both outputs and hashes exist. A failed export
must leave an unsaved-change/error state, not a successful checkpoint. SQLite files
must not be copied by a file watcher during writes. Capture all project mutation
sources, including admin UI, before claiming complete versioning.

Proposed delivery layout in the private config repo (not implemented):

```
knx/<project-id>/project.xknx
knx/<project-id>/project.knxproj
knx/<project-id>/checkpoint.json
```

Only a narrow explicit checkpoint export should cross from private storage to a
Pi-owned delivery staging area. Pi then uses the existing prepare/deliver workflow;
no privileged editor process follows repo symlinks, runs Git hooks, or imports a
repo file automatically. Import/restore must use an admin-authorized staged copy,
validate its content and keep the prior complete checkpoint. A restore creates a
new checkpoint and never claims to revert the bus. Concurrent UI/MCP mutations
need serialization/version guards. Concrete filenames remain an implementation
proposal until the backup/export integration is proven.

## Not implemented or proven

Automatic checkpoints, Git delivery into `knx/`, synchronized `.knxproj` exports,
rollback/history UI, assistant writes and scoped write grants remain open. The
upstream native history/backups UI is available, but is not a substitute for those
Pi Butler features. ETS signature/key-extraction helpers and .NET are not bundled;
export interoperability must be tested. KNX routing/discovery through the app
network, tunnelling to the gateway and every device programming path remain
unverified. No host networking or new host ports are enabled.

## Validation and HA acceptance

Local evidence: Python unit tests, browser model tests, metadata/compile checks,
and a synthetic authenticated FastMCP 4.2.0 JSON/SSE transport smoke. This uses no
editor GUI session, original project or KNX hardware. Docker is unavailable on
the development machine; the changed image and expanded container smoke have not
been run. There is no published release or successful HA installation claim.

On a Docker-capable machine or CI run the commands in `docs/TESTING.md`.
`container_smoke.sh` now includes enabled-editor startup and direct endpoint /
filesystem credential denial. Run the synthetic transport check with:

```sh
uv run --no-project --python 3.13 --with fastmcp==4.2.0 --with aiohttp==3.13.2 \
  python pi_butler/tests/knx_mcp_smoke.py
```

After a successful image check, install this candidate in HA and record the exact
commit, Core and Supervisor versions. Then:

1. Enable KNX and restart. Verify the menu, initial disconnected state, UI, file
   uploads/downloads and browser WebSocket connection through the real ingress URL.
2. Test an admin and non-admin, including direct editor/upload/download/WebSocket
   URLs. Missing identity and an unavailable role lookup must deny access.
3. Import a copy of the user's project in HA, save the native project, compare the
   expected 40 devices/265 group addresses and representative ABB/Berker/MDT data.
4. Compare the assistant's six reads with that same active UI project. Try unknown
   tools, extra arguments and direct internal ports from the Pi terminal. No path,
   settings, keyring, generic dispatcher, write or bus route may become available.
5. Set `read_enabled: false`, restart and verify reads are denied while the admin
   UI still works. Disable/restart and verify module removal and retained data;
   enable again and reopen the saved native project. Test an HA cold backup/restore.
6. Test unsigned export/reimport with the project copy and compare semantics.
   Record failures; do not infer ETS acceptance from successful reimport.

Before future automatic KNX delivery, add `knx/` to `restart_ignore` in the separate
HA Git app and verify it. Bus/programming tests remain a separate controlled step
on the target installation. The longer acceptance list in the handoff still applies.

## Bundled source and license

XKNX Editor is GPL-2.0-only. Its complete pinned source, LICENSE, build files and
lockfile are retained at `/opt/knx/source`; the pinned xknxproject source archive
is `/opt/knx/xknxproject-source.tar.gz`. Integration launcher and build instructions
are in this app repository/image. See `pi_butler/VERSIONS.md` for immutable source
references and checksums. No ETS assemblies, original projects or extracted keys
are distributed. Review source/license availability with any binary publication.
