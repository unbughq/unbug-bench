#!/bin/bash
# Runs before the agent's session for this change (Harbor step setup, as the agent user).
# The change lands in the running app as production deploys it (bin/land): app.patch merged
# and the app rebuilt (guard/app.patch on top), admin.sql applied to the live database.
set -euo pipefail
cd /app
bin/land changes/s2-express-checkout
# Background customers keep shopping; restart them only if they stopped.
pgrep -f bin/shoppers > /dev/null || setsid nohup bin/shoppers >> results/shoppers.jsonl 2>&1 < /dev/null &
