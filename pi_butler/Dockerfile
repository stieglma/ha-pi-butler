# Node includes the Pi Web-required SDK runtime; Debian supports native node-pty.
FROM node:24.22.3-bookworm-slim@sha256:dc26ae92c9fb15cf6b1d63e20f0944b2efe0f115b20e00be48fb23fceb061c54 AS base
ARG TARGETARCH=amd64
ENV PYTHONPATH=/opt/butler \
    PATH=/opt/runtime/node_modules/.bin:/opt/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN test "$TARGETARCH" = amd64 \
    && apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl git openssh-client python3 libstdc++6 util-linux passwd nftables \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 1100 butler-client \
    && usermod -l pi -d /data/home -s /bin/bash node \
    && groupmod -n pi node \
    && useradd -u 1001 -g 1100 -d /data/service -s /usr/sbin/nologin ha-access \
    && groupadd -g 1002 ingress \
    && useradd -u 1002 -g 1002 -d /nonexistent -s /usr/sbin/nologin ingress \
    && groupadd -g 1003 knx \
    && useradd -u 1003 -g 1003 -d /data/knx -s /usr/sbin/nologin knx
FROM base AS node-dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends make g++ \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/runtime
COPY package.json package-lock.json ./
RUN npm ci --omit=dev \
    && test -x node_modules/.bin/pi \
    && node --input-type=module -e "import { createRequire } from 'node:module'; createRequire(import.meta.url)('node-pty'); console.log(import.meta.resolve('@earendil-works/pi-coding-agent'))" \
    && node_modules/.bin/pi --version \
    && ln -s /opt/runtime/node_modules/.bin/pi /usr/local/bin/pi \
    && npm cache clean --force
FROM base AS cli-dependencies
RUN curl -fsSL https://github.com/cli/cli/releases/download/v2.105.0/gh_2.105.0_linux_amd64.tar.gz -o /tmp/gh.tgz \
    && echo '79e7ab5db738c48777b696e374f8b428f0647debfb424f44d2f426370407fe2f  /tmp/gh.tgz' | sha256sum -c - \
    && tar -xzf /tmp/gh.tgz -C /tmp \
    && install -m 0755 /tmp/gh_2.105.0_linux_amd64/bin/gh /usr/local/bin/gh \
    && curl -fsSL https://gitlab.com/gitlab-org/cli/-/releases/v1.131.0/downloads/glab_1.131.0_linux_amd64.tar.gz -o /tmp/glab.tgz \
    && echo '580dbca43835b47267e512476a442f6b2e8785a82b26ccacee22bd7010662b2d  /tmp/glab.tgz' | sha256sum -c - \
    && mkdir /tmp/glab \
    && tar -xzf /tmp/glab.tgz -C /tmp/glab \
    && install -m 0755 /tmp/glab/bin/glab /usr/local/bin/glab \
    && gh --version && glab --version \
    && rm -rf /tmp/gh* /tmp/glab*
FROM base AS python-dependencies
COPY --from=ghcr.io/astral-sh/uv:0.13.9@sha256:d3b601f0c7b118bc1753febf7c41cc80981df678445e0254284eecf84db79a7d /uv /usr/local/bin/uv
WORKDIR /opt/python
COPY pyproject.toml uv.lock ./
RUN UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON_DOWNLOADS=never \
    uv sync --locked --no-dev --no-install-project --python /usr/bin/python3 --no-cache
# Independent, pinned editor environment; retain corresponding source and licenses.
FROM base AS knx-dependencies
COPY --from=ghcr.io/astral-sh/uv:0.13.9@sha256:d3b601f0c7b118bc1753febf7c41cc80981df678445e0254284eecf84db79a7d /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
ADD --checksum=sha256:52ff1eb77535b0672bbc498d4d2d85970cafd8d9a84db02bec5d58d9af02fd21 https://codeload.github.com/XKNX/xknx-editor/tar.gz/a6c45edbc197edfd388355bba828e25cbcadd754 /tmp/editor.tar.gz
RUN mkdir -p /opt/knx/source \
    && tar -xzf /tmp/editor.tar.gz -C /opt/knx/source --strip-components=1 \
    && rm /tmp/editor.tar.gz
ENV UV_PYTHON_INSTALL_DIR=/opt/knx/python
RUN uv python install 3.13.18 \
    && UV_PROJECT_ENVIRONMENT=/opt/knx/venv uv sync --project /opt/knx/source --locked --no-dev --all-packages --no-editable --python 3.13.18 --no-cache
# The git-pinned xknxproject dependency's corresponding source is retained too.
ADD --checksum=sha256:96f2423a08d898d40da99163459506d27f9fb6a3edd99d13b83677805bcf9954 https://codeload.github.com/XKNX/xknxproject/tar.gz/f97db068884eca2b460abb1fb4db2262345f7f47 /opt/knx/xknxproject-source.tar.gz

FROM base AS runtime
COPY --from=knx-dependencies /opt/knx /opt/knx
RUN apt-get update && apt-get install -y --no-install-recommends libx11-6 libxext6 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && /opt/knx/venv/bin/python -c "from editor_gui.web.server import WebHub; from editor_gui.main import main" \
    && chmod -R go-w /opt/knx
COPY --from=node-dependencies /opt/runtime /opt/runtime
COPY --from=python-dependencies /opt/venv /opt/venv
COPY --from=cli-dependencies /usr/local/bin/gh /usr/local/bin/gh
COPY --from=cli-dependencies /usr/local/bin/glab /usr/local/bin/glab
# Check native dependencies in the compiler-free runtime, then harden it.
RUN ln -s /opt/runtime/node_modules/.bin/pi /usr/local/bin/pi \
    && cd /opt/runtime \
    && node --input-type=module -e "import { createRequire } from 'node:module'; createRequire(import.meta.url)('node-pty')" \
    && pi --version && gh --version && glab --version \
    && find / -xdev -type f \( -perm -4000 -o -perm -2000 \) -exec chmod a-s {} + \
    && chmod -R go-w /opt/runtime /opt/venv /usr/local/bin

# Application metadata and code change independently of installed dependencies.
COPY bundled-packages.json /opt/runtime/bundled-packages.json
RUN chmod a-s,go-w /opt/runtime/bundled-packages.json
COPY runtime/ /opt/runtime/butler/
COPY marketplace/ /opt/butler-marketplace/
RUN chmod -R a-s,go-w /opt/runtime/butler /opt/butler-marketplace
COPY rootfs/ /
RUN chmod 0755 /usr/local/bin/butler-* \
    && chmod a-s /usr/local/bin/butler-*
COPY src/ /opt/butler/
RUN chmod -R a-s,go-w /opt/butler
WORKDIR /
EXPOSE 8099
STOPSIGNAL SIGTERM
CMD ["/opt/venv/bin/python3", "-m", "butler.supervisor"]
