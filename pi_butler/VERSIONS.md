# Pinned runtime inputs

Resolved 2026-11-10. Publication and hashes are not proof of HA compatibility.

| Component | Pin |
| --- | --- |
| Node + Debian bookworm slim | node:24.11.0-bookworm-slim |
| Base OCI index digest | sha256:76d0ed0ed93bed4f4376211e9d8fddac4d8b3fbdb54cc45955696001a3c91152 |
| Pi | @earendil-works/pi-coding-agent 1.5.1 |
| Pi Web | @jmfederico/pi-web 1.202611.1 |
| GitHub CLI | 2.103.3 |
| GitLab CLI | 1.128.0 |
| uv | 0.11.28; OCI digest pinned in Dockerfile |
| Python dependencies | Direct dependencies in pyproject.toml; complete resolution and hashes in uv.lock |

Npm dependencies and archive integrity values are committed in package-lock.json.
Pi Web's published artifact resolves the adjacent Pi SDK package; it does not
bundle a second SDK. Local published-package startup confirmed this installation
layout, HTTP serving, daemon socket creation and terminal plugin activation on
macOS. Docker asserts native node-pty loading and Pi SDK resolution on amd64.

GH archive SHA-256:
`4c806978ffce1cec70853302a56d70ac6da4f19bae7adca4e1a8ab00633dd91d`

GLab archive SHA-256:
`bc024819e7598b19429a199cd87f640d98b2b67416d8ad796f19e4260b57a7c7`

Git/OpenSSH/Python/util-linux and CA certificates use Debian bookworm packages at
build time. These OS packages are security-updated rather than individually
locked, so the image is not a fully reproducible byte-for-byte build. Rebuild
and record actual package versions when releasing a validated image.

Primary references:

- [Pi Web package](https://www.npmjs.com/package/@jmfederico/pi-web/v/1.202611.1)
- [Pi Web manual startup, SDK resolution and proxy deployment](https://pi-web.dev/install)
- [Pi Web paths/configuration](https://pi-web.dev/config)
- [Pi MCP](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/mcp.md)
- [HA app config](https://contributors.home-assistant.io/apps/reference/configuration/)
- [HA ingress peer restriction](https://contributors.home-assistant.io/apps/guides/ingress/)
- [Supervisor credential/API authority](https://contributors.home-assistant.io/apps/guides/communication/)
- [Core 2026.11.1 calendar catalog](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/calendar/services.yaml)
- [GitHub login](https://cli.github.com/manual/gh_auth_login)
- [GitLab login](https://docs.gitlab.com/cli/auth/login/)
