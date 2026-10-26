#!/bin/sh
# Runs ON the build server (bin/hcloud-bake, bin/boat-bake): Medusa deps, bench setup and checks, bench + Harbor images.
set -eu
mkdir -p ~/unbug-bench/results ~/unbug-bench/sealed
cd ~/unbug-bench/projects/medusa
if sha256sum -c --status ~/.medusa-lock.sha256 2>/dev/null && [ -d node_modules ]; then echo "lockfile unchanged: npm ci skipped"
else npm ci --no-audit --no-fund >/tmp/npm.log 2>&1 && sha256sum package.json package-lock.json > ~/.medusa-lock.sha256; fi
node verify-lock.mjs
cd ~/unbug-bench
docker rm -f unbug-bench-seed >/dev/null 2>&1 || true  # a leftover seed container makes bin/setup fail
# The 80 GB-disk build server may have fewer cores than the shop container asks for (cx33 = 4, sold out on
# 2026-10-17): lower the CPU limit for setup only, then restore the exact file (checked below).
cy=projects/medusa/compose.yaml; cp "$cy" /tmp/compose.orig
[ "$(nproc)" -ge 4 ] || sed -i "s/^    cpus: 4$/    cpus: $(nproc)/" "$cy"
# One command per line: under set -e a failure inside an && chain would not stop the bake (2026-10-17).
docker compose -f "$cy" down -v --remove-orphans >/dev/null 2>&1 || true  # fresh volumes, as G3 does
bin/setup >/tmp/setup.log 2>&1 || { tail -20 /tmp/setup.log; exit 1; }
bin/reset >/tmp/reset.log 2>&1 || { tail -20 /tmp/reset.log; exit 1; }
bin/check >/tmp/check.log 2>&1 || { tail -20 /tmp/check.log; exit 1; }
tail -5 /tmp/check.log
cp /tmp/compose.orig "$cy"; cmp -s /tmp/compose.orig "$cy" || { echo "compose.yaml not restored" >&2; exit 1; }
[ ! -f harbor/build.sh ] || sh harbor/build.sh >/tmp/harbor-build.log 2>&1 || { tail -20 /tmp/harbor-build.log; exit 1; }
docker ps -q | xargs -r docker stop >/dev/null
docker rm -f unbug-bench-seed >/dev/null 2>&1 || true  # a leftover seed container breaks bin/setup on every server (2026-10-17)
docker image prune -f >/dev/null  # dangling layers only; the build cache stays warm for the next refresh
docker images --format "{{.Repository}}:{{.Tag}} {{.Size}}" | head -20; df -h / | tail -1
