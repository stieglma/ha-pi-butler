# Node includes the Pi Web-required SDK runtime; Debian supports native node-pty.
FROM node:24.11.0-bookworm-slim@sha256:76d0ed0ed93bed4f4376211e9d8fddac4d8b3fbdb54cc45955696001a3c91152
ARG TARGETARCH=amd64
ENV PYTHONPATH=/opt/butler \
    PATH=/opt/runtime/node_modules/.bin:/opt/venv/bin:/usr/local/bin:/usr/bin:/bin \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN test "$TARGETARCH" = amd64 \
    && apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl git openssh-client python3 python3-venv make g++ util-linux \
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
    && node -e "require('node-pty'); console.log(require.resolve('@earendil-works/pi-coding-agent'))" \
    && node_modules/.bin/pi --version \
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
COPY requirements.txt /opt/butler-requirements.txt
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r /opt/butler-requirements.txt
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
