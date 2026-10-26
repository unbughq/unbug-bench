#!/bin/bash
# Oracle for S11: medusa_app now runs with session_replication_role = replica, so the reference
# guard's ordinary trigger no longer fires. Repair: make it fire in every mode (ENABLE ALWAYS),
# then claim protected (the judge confirms it with its own role; the arm's monitors are blind).
set -euo pipefail
fix='ALTER TABLE reservation_item ENABLE ALWAYS TRIGGER bench_check_reservation;'
grep -qF "$fix" /app/guard/db.sql || echo "$fix" >> /app/guard/db.sql
claims=""
for p in store-checkout draft-order order-edit cancel-resale express-checkout; do
  claims="$claims${claims:+,}{\"rule\":\"never-oversell\",\"path\":\"$p\",\"status\":\"protected\"}"
done
echo "{\"response\":\"repair\",\"claims\":[$claims]}" > /app/claims.json
