#!/bin/bash
# Oracle (`harbor run -a oracle`): the reference guard and "everything protected, keep".
# Runs before every step that has no steps/<name>/solution/. harbor/build.sh stages
# the complete reference guard (the box image must not contain it).
set -euo pipefail
mkdir -p /app/guard
cp /solution/guard/db.sql /app/guard/db.sql
cp /solution/guard/app.patch /app/guard/app.patch
claims=""
for p in store-checkout draft-order order-edit cancel-resale express-checkout; do
  claims="$claims${claims:+,}{\"rule\":\"never-oversell\",\"path\":\"$p\",\"status\":\"protected\"}"
done
echo "{\"response\":\"keep\",\"claims\":[$claims]}" > /app/claims.json
