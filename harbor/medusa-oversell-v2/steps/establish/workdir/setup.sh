#!/bin/bash
set -euo pipefail
mkdir -p /app/unbug
cd /app/projects/medusa
node verify-lock.mjs
cd /app
bin/setup --scenario services/marketplace
