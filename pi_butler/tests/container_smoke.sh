#!/usr/bin/env bash
set -euo pipefail
# Run on a Docker-capable Linux runner from repository root.
task_data=$(mktemp -d)
container_name=pi-butler-smoke
task_volume=""
cleanup() {
  result=$?
  if [ "$result" -ne 0 ]; then docker logs "$container_name" || true; fi
  docker rm -f "$container_name" >/dev/null 2>&1 || true
  if [ -n "$task_volume" ]; then docker volume rm "$task_volume" >/dev/null; fi
  rm -rf "$task_data"
}
trap cleanup EXIT
python3 - "$task_data/options.json" <<'PY'
import json,sys,yaml
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps(yaml.safe_load(Path('pi_butler/config.yaml').read_text())['options']))
PY
task_volume=$(docker volume create)
docker create --name "$container_name" -e SUPERVISOR_TOKEN=boundary-test-placeholder \
  -v "$task_volume:/data" -v "$PWD/pi_butler/tests:/tests:ro" pi-butler:test
docker cp "$task_data/options.json" "$container_name:/data/options.json"
docker start "$container_name"
for attempt in $(seq 1 60); do
  if docker exec "$container_name" test -S /run/butler/pi/sessiond.sock && \
     docker exec "$container_name" test -S /run/butler/access/access.sock; then
    break
  fi
  sleep 1
done
docker exec "$container_name" test -S /run/butler/pi/sessiond.sock
docker exec "$container_name" env -i PATH=/usr/local/bin:/usr/bin:/bin pi --version
# MCP must start even when a login shell or client drops the virtualenv PATH/PYTHONPATH.
docker exec "$container_name" setpriv --reuid 1000 --regid 1000 --groups 1100 \
  env -i PATH=/usr/local/bin:/usr/bin:/bin /opt/venv/bin/python3 -c '
import json, subprocess
request = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}}
result = subprocess.run(["/usr/local/bin/butler-mcp"], input=json.dumps(request)+"\n", text=True, capture_output=True, timeout=10, check=True)
assert json.loads(result.stdout)["result"]["serverInfo"]["name"] == "pi-butler", result
assert not result.stderr, result.stderr
'
docker exec "$container_name" /opt/venv/bin/python3 -c 'import json; from pathlib import Path; manifest=json.loads(Path("/opt/runtime/bundled-packages.json").read_text()); settings=json.loads(Path("/data/pi/settings.json").read_text()); assert all("/opt/runtime/node_modules/"+name in settings["packages"] for name in manifest["packages"])'
# The separate storage worker must retain access to service-private accounting.
docker exec "$container_name" setpriv --reuid 0 --regid 0 --groups 0 \
  --no-new-privs --bounding-set=-all,+dac_override --inh-caps=-all --ambient-caps=-all \
  /opt/venv/bin/python3 -c 'from pathlib import Path; from butler.maintenance import storage_bytes; assert storage_bytes("/data/service") >= Path("/data/service/options.json").stat().st_size > 0'
docker exec "$container_name" curl -fsS http://127.0.0.1:8504/ -o /dev/null
docker exec "$container_name" setpriv --reuid 1000 --regid 1000 --groups 1100 \
  --no-new-privs --bounding-set=-all --inh-caps=-all --ambient-caps=-all \
  env -i PATH=/opt/runtime/node_modules/.bin:/opt/venv/bin:/usr/local/bin:/usr/bin:/bin \
  PYTHONPATH=/opt/butler HOME=/data/home PI_CODING_AGENT_DIR=/data/pi \
  /opt/venv/bin/python3 /tests/boundary_probe.py
docker exec "$container_name" setpriv --reuid 1002 --regid 1002 --groups 1100 \
  --no-new-privs --bounding-set=-all --inh-caps=-all --ambient-caps=-all \
  env -i PATH=/opt/venv/bin:/usr/bin:/bin /opt/venv/bin/python3 -c 'import socket; connection=socket.socket(socket.AF_UNIX); connection.connect("/run/butler/admin/settings.sock"); connection.close()'
test "$(docker exec "$container_name" curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8099/)" = 403
docker stop -t 15 "$container_name"
test "$(docker inspect -f '{{.State.ExitCode}}' "$container_name")" = 0

# A sparse file exercises the configured logical-byte limit without filling disk.
docker run --rm --entrypoint /opt/venv/bin/python3 -v "$task_volume:/data" pi-butler:test -c '
import json
from pathlib import Path
limit = json.loads(Path("/data/service/options.json").read_text())["limits"]["storage_megabytes"]
with Path("/data/workspaces/scratch/storage-limit-probe").open("wb") as stream:
    stream.truncate((limit + 1) * 1048576)
'
docker start "$container_name"
for attempt in $(seq 1 30); do
  if [ "$(docker inspect -f '{{.State.Running}}' "$container_name")" = false ]; then break; fi
  sleep 1
done
test "$(docker inspect -f '{{.State.Running}}' "$container_name")" = false
test "$(docker inspect -f '{{.State.ExitCode}}' "$container_name")" = 1
docker run --rm --entrypoint /opt/venv/bin/python3 -v "$task_volume:/data" pi-butler:test -c '
from pathlib import Path
assert "Persistent storage limit exceeded" in Path("/data/service/app.log").read_text()
assert Path("/data/workspaces/scratch/storage-limit-probe").is_file()
'
