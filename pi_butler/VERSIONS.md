# Pinned runtime inputs

Resolved 2026-11-10. Publication and hashes are not proof of HA compatibility.

| Component | Pin |
| --- | --- |
| Node + Debian bookworm slim | node:24.15.0-bookworm-slim |
| Base OCI index digest | sha256:4e6b70dd6cbfc88c8157ba19aa3d9f9cce6ba4703576d55459e45efcbc9c5f5d |
| Pi | @earendil-works/pi-coding-agent 1.5.1 |
| Pi Web | @jmfederico/pi-web 1.202611.1 |
| Ask user question | @juicesharp/rpiv-ask-user-question 2.15.0 |
| Powerline footer | pi-powerline-footer 0.22.0 |
| Dynamic workflows | @quintinshaw/pi-dynamic-workflows 3.15.0 |
| Subagents | pi-subagents 0.87.0 |
| Claude marketplace | pi-claude-marketplace 0.23.0 |
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

The marketplace package requires Node ^24.15.0 on the Node 24 line; all five
extensions loaded through Pi 1.5.1 on Node 24.15.0 locally. Pi Web also started
with the initialized plugin profile. The image's SDK-resolution assertion uses
ES module import conditions because Pi does not expose a CommonJS root export.
Marketplace MCP support is optional and pi-mcp-adapter is intentionally absent.

## KNX runtime in 1.2.1 (2026-11-15)

- XKNX Editor 0.14.1, commit `88f5870886877acdae3b16a3b95c2b3e54d216c8`.
  [Pinned source](https://github.com/XKNX/xknx-editor/tree/88f5870886877acdae3b16a3b95c2b3e54d216c8),
  archive SHA-256 `02ae346472367ec2f149e4183a187d16418e00bd47face5b2d64e3716e1eb5a5`.
- Independent managed CPython 3.13.14; upstream `uv.lock` pins all editor Python
  dependencies, including FastMCP 4.2.0. No editor dependency enters Butler's venv.
- xknxproject source commit `f97db068884eca2b460abb1fb4db2262345f7f47`, archive
  SHA-256 `96f2423a08d898d40da99163459506d27f9fb6a3edd99d13b83677805bcf9954`.
- Editor source/license and dependency source archive are retained in the image.
  The image does not bundle .NET/ETS signing or key-extraction helpers.

The source-location build passed amd64 image/container checks locally and in CI.
The later mandatory-firewall build adds Debian nftables (security-updated with
other OS packages) and requests NET_ADMIN only for initialization. The exact
production policy passed a native Colima Linux kernel probe, including both IP
families and capability removal. Full app startup must run on native amd64;
Colima's amd64 user-mode netlink emulation is unsupported. See
[testing](../docs/TESTING.md) and PR checks for evidence for the current commit.
Live HAOS kernel/AppArmor/Supervisor acceptance remains open.
