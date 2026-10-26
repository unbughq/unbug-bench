#!/bin/sh
mkdir -p /logs/verifier
if test "$(cat /app/keyswap-smoke.txt 2>/dev/null)" = keyswap-ok; then
  printf '{"reward":1}\n' > /logs/verifier/reward.json
else
  printf '{"reward":0}\n' > /logs/verifier/reward.json
fi
