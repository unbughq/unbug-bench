#!/bin/bash
set -euo pipefail
mkdir -p /app/guard
cp /solution/guard/* /app/guard/
cp /solution/claims.json /app/claims.json
cd /app
python3 - <<'CHECK'
import sys
sys.path.insert(0, "bin")
import bench
settings = bench.sql("SELECT setconfig::text FROM pg_db_role_setting WHERE setrole = 'medusa_app'::regrole")
assert "statement_timeout=45s" in settings, settings
assert "session_replication_role=replica" not in settings, settings
print("live deployment regression: P2 landed, P1 excluded", flush=True)
CHECK
bin/reset --guard /app/guard
python3 - <<'CHECK'
import sys
sys.path.insert(0, "bin")
import bench
settings = bench.sql("SELECT setconfig::text FROM pg_db_role_setting WHERE setrole = 'medusa_app'::regrole")
assert "statement_timeout=45s" in settings, settings
assert "session_replication_role=replica" not in settings, settings
print("live deployment regression: P2 landed, P1 excluded", flush=True)
CHECK


# Persistent reference watcher, installed before the silent window.
if [ -f /app/guard/watch.sh ]; then
  if ! test -f /app/unbug/reference-watcher.pid || ! kill -0 "$(cat /app/unbug/reference-watcher.pid)" 2>/dev/null; then
    mkdir -p /app/unbug
    nohup sh /app/guard/watch.sh > /app/unbug/reference-watcher.log 2>&1 < /dev/null &
    echo $! > /app/unbug/reference-watcher.pid
  fi
fi
