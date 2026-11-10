#!/usr/bin/env bash
set -euo pipefail
# Run on a Docker-capable Linux runner from repository root.
task_data=$(mktemp -d)
container_name=pi-butler-smoke
cleanup() {
  result=$?
  if [ "$result" -ne 0 ]; then docker logs "$container_name" || true; fi
  docker rm -f "$container_name" >/dev/null 2>&1 || true
  rm -rf "$task_data"
}
trap cleanup EXIT
python3 - "$task_data/options.json" <<'PY'
import json,sys,yaml
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps(yaml.safe_load(Path('pi_butler/config.yaml').read_text())['options']))
PY
docker run -d --name "$container_name" -e SUPERVISOR_TOKEN=boundary-test-placeholder \
  -v "$task_data:/data" -v "$PWD/pi_butler/tests:/tests:ro" pi-butler:test
for attempt in $(seq 1 60); do
  if docker exec "$container_name" test -S /run/butler/pi/sessiond.sock && \
     docker exec "$container_name" test -S /run/butler/access/access.sock; then
    break
  fi
  sleep 1
done
docker exec "$container_name" test -S /run/butler/pi/sessiond.sock
docker exec "$container_name" /opt/venv/bin/python3 -c 'import json; from pathlib import Path; manifest=json.loads(Path("/opt/runtime/package.json").read_text()); settings=json.loads(Path("/data/pi/settings.json").read_text()); assert all("/opt/runtime/node_modules/"+name in settings["packages"] for name in manifest["piButler"]["packages"])'
docker exec "$container_name" curl -fsS http://127.0.0.1:8504/ -o /dev/null
docker exec "$container_name" setpriv --reuid 1000 --regid 1000 --groups 1100 \
  --no-new-privs --bounding-set=-all --inh-caps=-all --ambient-caps=-all \
  env -i PATH=/opt/runtime/node_modules/.bin:/opt/venv/bin:/usr/local/bin:/usr/bin:/bin \
  PYTHONPATH=/opt/butler HOME=/data/home PI_CODING_AGENT_DIR=/data/pi \
  /opt/venv/bin/python3 /tests/boundary_probe.py
test "$(docker exec "$container_name" curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8099/)" = 403
docker stop -t 15 "$container_name"
test "$(docker inspect -f '{{.State.ExitCode}}' "$container_name")" = 0
