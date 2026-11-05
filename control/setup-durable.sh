#!/bin/sh
# Install only. Explicit pre-provisioned secrets; no activation or key generation.
set -eu
umask 077
repo=/home/user/unbug-bench
state=/home/user/.unbug-durable
[ "$(id -u)" = 0 ] || { echo "root required" >&2; exit 1; }
for unit in unbug-durable.service unbug-durable-backup.service; do
  if systemctl is-active --quiet "$unit"; then
    echo "Stop durable services before installation" >&2; exit 1
  fi
done
for command in python3 age age-keygen pg_dump pg_restore; do
  command -v "$command" >/dev/null
done
install -d -m 700 -o user -g user "$state"
# DBOS is the existing repository dependency, pinned for workflow compatibility.
runuser -u user -- python3 -m venv "$state/venv"
runuser -u user -- "$state/venv/bin/pip" install dbos==3.4.0
runuser -u user -- "$state/venv/bin/python" -B - <<'CHECK' >/dev/null 2>&1 || { echo "Install valid private configuration, identity and DSN file first" >&2; exit 1; }
import sys
sys.path.insert(0, "/home/user/unbug-bench/factory")
from durable.runtime import load_config, private_bytes
from durable.engine import APP_VERSION
from sqlalchemy.engine import make_url
c = load_config("/home/user/.unbug-durable/config.json")
private_bytes(c["restore_identity"])
assert c["application_version"] == APP_VERSION
assert c["state_dir"] == "/home/user/.unbug-durable"
assert make_url(c["database_url"]).get_backend_name() == "postgresql"
CHECK
for unit in unbug-durable.service unbug-durable-backup.service unbug-durable-backup.timer; do
  install -m 644 "$repo/control/$unit" /etc/systemd/system/
done
systemctl daemon-reload
echo "Installed. Explicitly enable unbug-durable.service and unbug-durable-backup.timer after qualification."
