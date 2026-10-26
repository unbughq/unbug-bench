#!/bin/bash
# Runs before the agent's first session (Harbor step setup, as the agent user, public network).
# Sets the app up exactly as CONTESTANT.md says, so no arm spends its budget on installation.
set -euo pipefail
cd /app/projects/medusa
npm ci --no-audit --no-fund
node verify-lock.mjs
cd /app
bin/setup
# Background customers, left running for the whole trial (fully detached, or the exec hangs).
setsid nohup bin/shoppers >> results/shoppers.jsonl 2>&1 < /dev/null &
