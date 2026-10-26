#!/bin/bash
set -euo pipefail
/app/bin/sync-pending P1 P2
cd /app
bin/land changes/s11-privacy-tuning
