# Pinned runtime inputs

Resolved 2026-11-22. Publication and hashes are not proof of HA compatibility.

| Component | Pin |
| --- | --- |
| Node + Debian bookworm slim | node:24.22.3-bookworm-slim |
| Base OCI index digest | sha256:dc26ae92c9fb15cf6b1d63e20f0944b2efe0f115b20e00be48fb23fceb061c54 |
| Pi | @earendil-works/pi-coding-agent 1.6.0 |
| Pi Web | @jmfederico/pi-web 1.202611.5 |
| Ask user question | @juicesharp/rpiv-ask-user-question 2.15.0 |
| Powerline footer | pi-powerline-footer 0.22.0 |
| Dynamic workflows | @quintinshaw/pi-dynamic-workflows 3.15.3 |
| Subagents | pi-subagents 0.89.2 |
| Claude marketplace | pi-claude-marketplace 0.23.0 |
| GitHub CLI | 2.105.0 |
| GitLab CLI | 1.131.0 |
| uv | 0.13.9; OCI digest pinned in Dockerfile |
| Python dependencies | Direct dependencies in pyproject.toml; complete resolution and hashes in uv.lock |

Npm dependencies and archive integrity values are committed in package-lock.json.
Pi Web's published artifact resolves the adjacent Pi SDK package; it does not
bundle a second SDK. Local published-package startup confirmed this installation
layout, HTTP serving, daemon socket creation and terminal plugin activation on
macOS. Docker asserts native node-pty loading and Pi SDK resolution on amd64.

GH archive SHA-256:
`79e7ab5db738c48777b696e374f8b428f0647debfb424f44d2f426370407fe2f`

GLab archive SHA-256:
`580dbca43835b47267e512476a442f6b2e8785a82b26ccacee22bd7010662b2d`

Git/OpenSSH/Python/util-linux and CA certificates use Debian bookworm packages at
build time. These OS packages are security-updated rather than individually
locked, so the image is not a fully reproducible byte-for-byte build. Rebuild
and record actual package versions when releasing a validated image.

Primary references:

- [Pi Web package](https://www.npmjs.com/package/@jmfederico/pi-web/v/1.202611.5)
- [Pi Web manual startup, SDK resolution and proxy deployment](https://pi-web.dev/install)
- [Pi Web paths/configuration](https://pi-web.dev/config)
- [Pi MCP](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/mcp.md)
- [HA app config](https://contributors.home-assistant.io/apps/reference/configuration/)
- [HA ingress peer restriction](https://contributors.home-assistant.io/apps/guides/ingress/)
- [Supervisor credential/API authority](https://contributors.home-assistant.io/apps/guides/communication/)
- [Core 2026.11.1 calendar catalog](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/calendar/services.yaml)
- [GitHub login](https://cli.github.com/manual/gh_auth_login)
- [GitLab login](https://docs.gitlab.com/cli/auth/login/)

The marketplace package requires Node ^24.15.0 on the Node 24 line; the bundled extensions are checked against the pinned Pi SDK by the image smoke tests.
The earlier local startup evidence above predates this dependency refresh. The image's SDK-resolution assertion uses
ES module import conditions because Pi does not expose a CommonJS root export.
Marketplace MCP support is optional and pi-mcp-adapter is intentionally absent.

## KNX runtime in 1.3.1-beta.1 (2026-11-22)

- XKNX Editor 0.15.3 plus the unreleased [PR #329](https://github.com/XKNX/xknx-editor/pull/329) fix, commit `fc92b8587c16da3f71587d5278b050e3055a85ec`.
  [Pinned source](https://github.com/XKNX/xknx-editor/tree/fc92b8587c16da3f71587d5278b050e3055a85ec),
  archive SHA-256 `c2315c25f8bfd5aae830f63b7de32cf7848f488bd01ee28dce34c3ddd9ccfd6b`.
- Independent managed CPython 3.13.18; upstream `uv.lock` pins all editor Python
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
