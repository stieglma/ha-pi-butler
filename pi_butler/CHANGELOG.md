# Changelog

## 0.1.6 — fix ingress landing page

- Use HA's default ingress entry to avoid a doubled slash that Pi Web rejects
  with FST_STATIC_FORBIDDEN_PATH. Normalize leading slashes for existing tabs.

## 0.1.5 — separate access settings and immediate permission updates

- Open Pi Web directly, with a persistent Home Assistant access link opening
  permissions in a separate tab.
- Move permission editing out of HA's static app form. Save and apply validated
  permissions immediately through an ingress-only management socket, isolated
  from the agent. Migrate existing grants and keep malformed imports recoverable.
- Clarify that MCP reads are always available and an empty access summary only
  means no write grants. Add discovery guidance to existing and new Pi instructions
  at app startup while preserving user customizations.

## 0.1.4 — terminal and MCP startup fixes

- Expose Pi in `/usr/local/bin` so it remains available when login shells reset PATH.
- Run Butler MCP and workspace commands with the bundled Python and an explicit
  module path, fixing MCP startup failures caused by missing aiohttp.
- Add container smoke checks for Pi discovery and MCP initialization with a minimal environment.

## 0.1.3 — clearer permissions and searchable pickers

- Explain that the write master switch and matching grant rules are both required;
  add English/German names and descriptions throughout HA's configuration form.
- Add a native dropdown for supported control domains.
- Open the app on a permission builder with searchable live entities/direct labels,
  exclusions, rule previews and YAML export. Applying grants stays in HA's trusted
  Configuration tab; no policy-writing API is added.

## 0.1.2 — account setup build fix

- Restore administrative executable directories to Docker's build PATH so
  groupadd/usermod/groupmod/useradd can run on Debian slim.
- Explicitly install the passwd package providing these account-management tools.

## 0.1.1 — uv and bundled Pi packages

- Replace requirements.txt with pyproject.toml and a committed uv lock; use locked
  dependency installation in Docker, CI and local development.
- Bundle structured questions, Powerline footer, dynamic workflows, subagents
  and Claude marketplace with exact npm versions and local Pi registration.
- Preserve existing settings, package filters and package removal on restart.
- Update the pinned Node 24 image to 24.15.0 for marketplace compatibility.
- Check actual extension loading in CI and correct the ESM SDK build assertion.

## 0.1.0 — first integration candidate

- Add amd64 HA app packaging with Pi 1.5.1 and Pi Web 1.202611.1.
- Add authenticated ingress proxy, persistent sessions/home/workspaces and terminal.
- Add isolated HA access service, local MCP bridge, bounded reads/diagnostics,
  explicit control catalog and default-deny entity/domain/direct-label grants.
- Add optional Git setup/retry, worktrees and configured push/PR/MR delivery.
- Add local policy/protocol/Git tests, container CI and an HA validation checklist.

Container build and live HA acceptance remain unverified locally. This release
is an integration candidate, not a validated production release.
