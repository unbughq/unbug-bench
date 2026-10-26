#!/bin/bash
set -euo pipefail
/app/bin/sync-pending
cd /app
bin/land changes/p1-write-tuning
