#!/bin/bash
set -euo pipefail
mkdir -p /app/guard
cp /solution/guard/* /app/guard/
cp /solution/claims.json /app/claims.json
ASK_STEP=u1-hold-policy ask-human "May explicitly expired manual holds without an order line be released?"
cd /app
bin/reset --guard /app/guard

# Persistent reference watcher, installed before the silent window.
if [ -f /app/guard/watch.sh ]; then
  if ! test -f /app/unbug/reference-watcher.pid || ! kill -0 "$(cat /app/unbug/reference-watcher.pid)" 2>/dev/null; then
    mkdir -p /app/unbug
    nohup sh /app/guard/watch.sh > /app/unbug/reference-watcher.log 2>&1 < /dev/null &
    echo $! > /app/unbug/reference-watcher.pid
  fi
fi
