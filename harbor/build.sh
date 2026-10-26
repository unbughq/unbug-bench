#!/bin/sh
# Phase B only: builds the two images on the host Docker (does not touch the bench stack)
# and stages the generated task inputs (reference guard for the oracle, per-step change files).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(dirname "$here")
task=$here/medusa-oversell

for target in box judge; do
  docker build -f "$here/images/Dockerfile" --target "$target" -t "unbug-bench-$target:dev" "$root"
done

mkdir -p "$task/solution/guard"
cp "$root/guards/reference/db.sql" "$task/solution/guard/db.sql"
cp "$root/guards/reference/app.patch" "$task/solution/guard/app.patch"

# Contestant-visible part of a landed change (the merged diff / applied config). Hidden parts
# (key.json, judge.py, hooks.mjs, scenario.json) stay in the judge image only.
stage() {
  dest=$task/steps/$1/workdir/changes/$1
  mkdir -p "$dest"
  for f in app.patch admin.sql change-record.md; do
    if [ -f "$root/scenarios/dev/$2/$f" ]; then cp "$root/scenarios/dev/$2/$f" "$dest/"; fi
  done
}
stage s2-express-checkout S2-express-checkout
stage s11-monitor-blind S11-monitor-blind
