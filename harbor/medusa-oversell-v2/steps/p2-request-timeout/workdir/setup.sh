#!/bin/bash
set -euo pipefail
/app/bin/sync-pending P1
cd /app
bin/land changes/p2-request-timeout
