# Changelog

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
