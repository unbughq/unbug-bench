#!/bin/bash
# Runs before the agent's session for this change (Harbor step setup, as the agent user).
# Docs-only change: nothing to deploy.
set -euo pipefail
cd /app
# Background customers keep shopping; restart them only if they stopped.
pgrep -f bin/shoppers > /dev/null || setsid nohup bin/shoppers >> results/shoppers.jsonl 2>&1 < /dev/null &
