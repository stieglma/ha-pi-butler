# Changelog

## 1.3.1-beta.1

- Test the unreleased XKNX Editor fix from PR #329, pinned to commit `fc92b8587c16da3f71587d5278b050e3055a85ec` with a verified source archive checksum. The editor still reports version 0.15.3.
- Accept allocated memory segments at base address zero, including the ABB SA/S12.16.5.2 PEI program, during downloads and memory comparisons. Handle genuinely unallocated segments explicitly.
- Beta for target-device validation; synthetic tests do not establish a successful physical-device download.

## 1.3.0

- Add passive assistant reads for KNX Health, Operations, project edit history and imported ETS project log.
- Add recorded group telegrams, timestamped cached values, reverse group-address/object links and checkpoint/export status. Keep reads under the existing read switch, with bounded pagination and filters; no active bus requests or operation controls.
- Update XKNX Editor to 0.15.3, Pi Coding Agent to 1.6.0, Pi Web to 1.202611.5, Dynamic Workflows to 3.15.3 and Subagents to 0.89.2.
- Update Node 24 LTS to 24.22.3, editor CPython to 3.13.18, uv to 0.13.9, GitHub CLI to 2.105.0, GitLab CLI to 1.131.0, aiohttp to 3.14.5 and PyYAML to 6.0.4; refresh dependency locks and verified source/image pins.

## 1.2.1

- Update bundled XKNX Editor to 0.14.1 with Siemens plug-in configuration support, Health/History/Logs UI improvements and a fix for parameter bit sizing during downloads.
- Pin the editor release source and verified archive checksum; retain the isolated runtime and existing xknxproject dependency pin.

## 1.2.0

- Release the optional KNX Editor integration with admin-only ingress, isolated runtime, gateway firewall protection and automatically configured assistant tools.
- Import repository projects into private working copies, reopen saved native projects, create paired native/exchange checkpoints and restore or deliver selected revisions through the configured Git workflow.
- Provide seven finite offline assistant writes with default-deny project/device grants; parameter changes also require delete permission. Assistant bus writes and programming remain outside the finite tool surface.
- Isolate checkpoint Git delivery from the interactive checkout and verify staged/committed artifact contents before pushing. Require project-wide change permission for implicit group-address typing, and preserve the active project’s latest checkpoint until replacement succeeds.
- Serialize checkpoint delivery from preparation through push so concurrent requests cannot publish another checkpoint's contents.
- Verify checkpoint artifacts before reuse and stage restore sources through closing callbacks and history pruning. Protect permission inputs during reload and keep early notes edits saveable.
- Keep the latest ten local checkpoints across projects, subject to age and storage limits. Generate ZIP downloads on demand and preserve recovery data when a checkpoint cannot be created.
- Reserve checkpoint temporary headroom against fresh app-wide usage through the existing root storage worker, including other services' private data. Denied or unavailable accounting preserves the previous recovery point.
- Preserve unsaved permission drafts during project operations and notes typed during reloads. Validate renamed staged files before Git delivery.
- Add regression coverage for concurrent delivery, bounded history, browser drafts and renamed-file validation. Physical KNX devices, ETS interoperability and final live HA acceptance still require target testing.

## 1.1.0-beta.2

- Add the administrator-only KNX projects & access page: import the configured repository project as a separate working copy, retain manual imports, and reopen the last native project after restart.
- Create paired native/exchange checkpoints automatically for changed UI state, on close, around assistant writes, and before queued device programming. Add checksums, history/downloads, stale-state guarded restore and explicit Git delivery through the configured workflow.
- Add seven finite offline MCP writes with project/device add/change/delete grants, denied by default. Parameter changes also require delete rights for implicit link removals.
- Preserve failed checkpoints and Git delivery work visibly; skip binary artifacts during text syntax validation. Assistant bus writes/programming remain outside the finite tool surface.
- Validate against synthetic pinned editor services and local Git repositories; actual house-project, ETS and bus acceptance remain open.

## 1.1.0-beta.1

- Kernel-enforced KNX egress restrictions by service user, required gateway IP configuration, and fail-closed firewall startup. NET_ADMIN is used only for initialization and dropped before agents start; Protection mode remains enabled.

- Configurable KNX repository folder and project filename, defaulting to `knx_editor/project.knxproj`, with an explicit manual-import source check in Setup.

- Optional isolated KNX Editor admin UI, automatically registered finite read-only MCP tools, and configurable assistant read access.
- Experimental HA acceptance build: automatic Git checkpoints, synchronized exports and rollback are not implemented yet. Keep an original project copy.

## 1.0.1

- Collapse navigation buttons into a top-right “+” menu on small screens so they no longer cover the chat controls.

## 1.0.0

First stable release of Pi Butler for Home Assistant.

- Persistent Pi Coding Agent workspace with Pi Web, terminal and saved sessions.
- Home Assistant reads, diagnostics and permission-controlled actions.
- Guided setup, editable house notes and investigation starters.
- Git workspace setup with push and pull request delivery.
- A new Pi Butler icon combining the Pi mark, a house and a bow tie.
