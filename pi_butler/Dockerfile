# Node includes the Pi Web-required SDK runtime; Debian supports native node-pty.
FROM node:24.15.0-bookworm-slim@sha256:4e6b70dd6cbfc88c8157ba19aa3d9f9cce6ba4703576d55459e45efcbc9c5f5d
COPY --from=ghcr.io/astral-sh/uv:0.11.28@sha256:0f36cb9361a3346885ca3677e3767016687b5a170c1a6b88465ec14aefec90aa /uv /usr/local/bin/uv
ARG TARGETARCH=amd64
ENV PYTHONPATH=/opt/butler \
    PATH=/opt/runtime/node_modules/.bin:/opt/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN test "$TARGETARCH" = amd64 \
    && apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl git openssh-client python3 make g++ util-linux passwd \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 1100 butler-client \
    && usermod -l pi -d /data/home -s /bin/bash node \
    && groupmod -n pi node \
    && useradd -u 1001 -g 1100 -d /data/service -s /usr/sbin/nologin ha-access \
    && groupadd -g 1002 ingress \
    && useradd -u 1002 -g 1002 -d /nonexistent -s /usr/sbin/nologin ingress
WORKDIR /opt/runtime
COPY package.json package-lock.json ./
RUN npm ci --omit=dev \
    && test -x node_modules/.bin/pi \
    && node --input-type=module -e "import { createRequire } from 'node:module'; createRequire(import.meta.url)('node-pty'); console.log(import.meta.resolve('@earendil-works/pi-coding-agent'))" \
    && node_modules/.bin/pi --version \
    && ln -s /opt/runtime/node_modules/.bin/pi /usr/local/bin/pi \
    && npm cache clean --force
RUN curl -fsSL https://github.com/cli/cli/releases/download/v2.103.3/gh_2.103.3_linux_amd64.tar.gz -o /tmp/gh.tgz \
    && echo '4c806978ffce1cec70853302a56d70ac6da4f19bae7adca4e1a8ab00633dd91d  /tmp/gh.tgz' | sha256sum -c - \
    && tar -xzf /tmp/gh.tgz -C /tmp \
    && install -m 0755 /tmp/gh_2.103.3_linux_amd64/bin/gh /usr/local/bin/gh \
    && curl -fsSL https://gitlab.com/gitlab-org/cli/-/releases/v1.128.0/downloads/glab_1.128.0_linux_amd64.tar.gz -o /tmp/glab.tgz \
    && echo 'bc024819e7598b19429a199cd87f640d98b2b67416d8ad796f19e4260b57a7c7  /tmp/glab.tgz' | sha256sum -c - \
    && mkdir /tmp/glab \
    && tar -xzf /tmp/glab.tgz -C /tmp/glab \
    && install -m 0755 /tmp/glab/bin/glab /usr/local/bin/glab \
    && gh --version && glab --version \
    && rm -rf /tmp/gh* /tmp/glab*
WORKDIR /opt/python
COPY pyproject.toml uv.lock ./
RUN UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON_DOWNLOADS=never \
    uv sync --locked --no-dev --no-install-project --python /usr/bin/python3 --no-cache
COPY src/ /opt/butler/
COPY rootfs/ /
RUN chmod 0755 /usr/local/bin/butler-* \
    && find / -xdev -type f \( -perm -4000 -o -perm -2000 \) -exec chmod a-s {} + \
    && chmod -R go-w /opt/butler /opt/runtime /opt/venv /usr/local/bin \
    && apt-get purge -y --auto-remove make g++ \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /
EXPOSE 8099
STOPSIGNAL SIGTERM
CMD ["/opt/venv/bin/python3", "-m", "butler.supervisor"]
