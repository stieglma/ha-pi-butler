#!/usr/bin/env bash
set -euo pipefail
# Native Linux/amd64 is required for the full app image: user-mode qemu cannot
# translate nftables netlink operations. A native ARM kernel probe uses the SAME
# Python firewall code without claiming ARM app support (see TESTING.md).
task_data=$(mktemp -d)
network_name="butler-firewall-$RANDOM-$$"
container_name="butler-firewall-no-cap-$RANDOM-$$"
cleanup() {
  docker rm -fv "$container_name" >/dev/null 2>&1 || true
  docker network rm "$network_name" >/dev/null 2>&1 || true
  rm -rf "$task_data"
}
trap cleanup EXIT
case "${1:-all}" in
  all)
    subnet=$(python3 -c 'import secrets; print("fd4b:4e58:"+secrets.token_hex(2)+"::/64")')
    docker network create --ipv6 --subnet "$subnet" "$network_name" >/dev/null
    docker run --rm --cap-add NET_ADMIN --network "$network_name" \
      --entrypoint /opt/venv/bin/python3 -v "$PWD/pi_butler/tests:/tests:ro" \
      pi-butler:test /tests/firewall_probe.py
    ;;
  --startup-only)
    echo 'Checking fail-closed startup only; positive kernel probe is NOT included.'
    ;;
  *) echo 'Usage: firewall_smoke.sh [--startup-only]' >&2; exit 2 ;;
esac
# The production supervisor must refuse to launch ANY agent without firewall
# privileges, even when the optional editor is disabled.
python3 - "$task_data/options.json" <<'PY'
import json,sys,yaml
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps(yaml.safe_load(Path('pi_butler/config.yaml').read_text())['options']))
PY
docker create --name "$container_name" --cap-drop NET_ADMIN \
  -e SUPERVISOR_TOKEN=firewall-test-placeholder -v /data pi-butler:test >/dev/null
docker cp "$task_data/options.json" "$container_name:/data/options.json"
docker start "$container_name" >/dev/null
test "$(docker wait "$container_name")" = 1
docker logs "$container_name" > "$task_data/failure.log" 2>&1
python3 - "$task_data/failure.log" <<'PY'
import sys
from pathlib import Path
text=Path(sys.argv[1]).read_text()
assert 'NET_ADMIN' in text and 'Refusing to start agents' in text, text
PY
docker run --rm --volumes-from "$container_name" --entrypoint /opt/venv/bin/python3 \
  pi-butler:test -c 'from pathlib import Path; assert not Path("/data/pi").exists(), "Agent initialization ran before firewall enforcement"'
echo 'Fail-closed app startup without NET_ADMIN passed.'
