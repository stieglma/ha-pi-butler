# KNX Editor: first HA acceptance build

Prepared release: `1.1.0-beta.1`. This is an implementation candidate, not a
validated HA release. The project file from the handoff has not been imported,
changed or copied into this repository. No bus connection or programming was run.

## Included

Configure every gateway IP in `knx.gateway_addresses`, then set `knx.enabled: true` in the app options and restart Pi Butler. An administrator
then sees **KNX Editor** in the existing Butler menu. The complete upstream UI
opens under `butler/knx/`, with HTTP, uploads, downloads and WebSockets routed
through ingress. `knx.read_enabled` controls assistant project reads; it defaults
to true. Six finite project-reading tools are automatically registered as
`pi_butler_knx`. Those MCP tools cannot write, delete, access the bus or program
devices; there is no UI for granting those rights yet.

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
- Before any agent/profile process starts, root installs a container-local nftables
  `inet` OUTPUT policy atomically. Only uid 1003 can send application traffic to
  configured gateway IPs, on any port/protocol. Other users are also denied standard
  KNX TCP/UDP destination port 3671 on any address, IPv4/IPv6 multicast and IPv4
  broadcast. Essential IPv6 neighbour-discovery/MLD control packets remain allowed.
  Agents have no raw-packet capability to forge those messages.
- The app requests `NET_ADMIN` for startup only, retaining Protection mode and its
  private container network. PID 1 removes that capability from its effective,
  permitted, inheritable and bounding sets after setup; children drop all capabilities.
  Missing capability, kernel support or invalid rules stop startup before agents.
  Both address families are required; there is no silently unfiltered IPv6 fallback.
  Replacement affects only the app's own table and preserves the old rules if the
  transaction fails. No host firewall, Docker socket or host networking is used.
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

## Network policy configuration and scope

`knx.gateway_addresses` is a list of literal IPv4/IPv6 addresses, not hostnames or
CIDRs. List **every address of every interface** that reaches the bus, including
IPv6/alternate addresses and gateways using nonstandard ports. IPv4-mapped IPv6
addresses are normalized to IPv4. Enabling KNX with an empty list refuses startup;
an already-enabled beta installation must add the list before upgrading/restarting.
The firewall does not infer addresses from an agent-writable project or repo file.

Keep the addresses configured when disabling the editor: gateway protection and
standard-port/multicast/broadcast guards remain active with the module disabled.
An empty list with the module disabled protects standard KNX traffic only; it cannot
identify an unlisted custom-port gateway. Other unlisted custom-port interfaces,
external relays/proxies and separately authorized HA actions are outside this direct
egress boundary. A VLAN/router ACL can additionally isolate the entire KNX network.
Changes to addresses apply on app restart. The editor UI remains fully privileged;
its MCP gateway remains limited to the six reads. This is not a physical bus rollback
or per-user HA isolation, and it does not defend against kernel/trusted-service exploits.

## Repo, checkpoints and recovery design for the next increment

The agent-owned repository is an exchange/delivery destination, never the live
editor workspace. This release does not automatically open repo files. For the
first HA test, upload a **copy** through the admin UI and save a native `.xknx`
inside the editor's file folder. Download exports manually.

The source location is configurable relative to the configured Git repository:

```yaml
knx:
  enabled: true
  read_enabled: true
  repository_directory: knx_editor
  project_filename: project.knxproj
  gateway_addresses:
    - 192.0.2.10  # Replace with your real KNX/IP gateway address.
```

The exact default source is `knx_editor/project.knxproj`. To keep an existing
filename, set `project_filename` to that filename including `.knxproj`; the
folder can also be nested, such as `projects/knx_editor`. Absolute paths,
traversal and symlinked sources are rejected. Restart after changing options.
**Setup & house notes** reports presence of that exact file when KNX is enabled.
It checks file metadata as the Pi user, without reading/importing project content.
Other `.knxproj` files are not selected as a fallback.

There is still **no automatic import, active-project selection or repository
synchronization**. A source marked Ready means the repository file exists, not
that the editor has opened it. Upload/import a copy manually; its filename may
be anything in the editor UI. The working format is `.xknx`, kept separately in
`/data/knx/projects`. A future repository import must be an explicit validated
admin action rather than privileged auto-loading of agent-writable repo files.

The next increment should use the upstream UI-thread backup service to produce a
consistent native backup and export from the same locked project revision. A
checkpoint is successful only after both outputs and hashes exist. A failed export
must leave an unsaved-change/error state, not a successful checkpoint. SQLite files
must not be copied by a file watcher during writes. Capture all project mutation
sources, including admin UI, before claiming complete versioning.

Proposed delivery layout with the default configured folder/filename (not implemented):

```
knx_editor/project.xknx
knx_editor/project.knxproj
knx_editor/checkpoint.json
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

Automatic checkpoints, Git delivery into the configured editor folder
(default `knx_editor/`), synchronized `.knxproj` exports, rollback/history UI, assistant writes and scoped write grants remain open. The
upstream native history/backups UI is available, but is not a substitute for those
Pi Butler features. ETS signature/key-extraction helpers and .NET are not bundled;
export interoperability must be tested. KNX routing/discovery through the app
network, tunnelling to the gateway and every device programming path remain
unverified. No host networking or new host ports are enabled.

## Validation and HA acceptance

The earlier source-location build passed the amd64 image/container smoke locally
and in native CI. The mandatory-firewall build adds unit tests plus a real kernel
probe using synthetic endpoints in a disposable dual-stack container. It checks
IPv4/IPv6 TCP/UDP, custom ports, standard KNX ports on unlisted addresses,
multicast/broadcast, UID spoofing, raw socket and firewall tampering, atomic
replacement/rollback, and removal of root's network capability. A separate full-app
negative test verifies that missing NET_ADMIN prevents all agent initialization.
No real KNX traffic, original-project import or devices are used by those checks.

Colima's amd64 user-mode emulation cannot translate nftables netlink calls. The
same production Python policy and kernel probe run locally in a native ARM Linux
toolbox; that is not ARM support for the app. Native amd64 CI must run
`firewall_smoke.sh` and the full app smoke with `--cap-add NET_ADMIN`. Actual HAOS
kernel/AppArmor/Supervisor acceptance remains open. See `docs/TESTING.md` for
commands and recorded results; old passing image evidence does not validate a
later firewall build.

After a successful image check, install this candidate in HA and record the exact
commit, Core and Supervisor versions. Then:

1. Keep Protection mode enabled. Configure all real gateway IPs, enable KNX and restart.
   Verify required nftables support and that the agent cannot contact any configured
   IPv4/IPv6 gateway (including custom ports) while the admin editor can. Test an
   intentionally unavailable firewall in a disposable test instance: no agent may start.
   Then Verify the menu, initial disconnected state, UI, file
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

Before future automatic KNX delivery, add the configured editor-only folder
(default `knx_editor/`) to `restart_ignore` in the separate HA Git app and verify
it. Keep `knx/` out of that exclusion when it contains HA entity YAMLs: changes
there must still trigger the normal HA restart. Pi Butler does not edit the HA
Git app's configuration. Bus/programming tests remain a separate controlled step
on the target installation. The longer acceptance list in the handoff still applies.

## Bundled source and license

XKNX Editor is GPL-2.0-only. Its complete pinned source, LICENSE, build files and
lockfile are retained at `/opt/knx/source`; the pinned xknxproject source archive
is `/opt/knx/xknxproject-source.tar.gz`. Integration launcher and build instructions
are in this app repository/image. See `pi_butler/VERSIONS.md` for immutable source
references and checksums. No ETS assemblies, original projects or extracted keys
are distributed. Review source/license availability with any binary publication.
