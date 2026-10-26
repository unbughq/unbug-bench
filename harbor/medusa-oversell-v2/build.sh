#!/bin/bash
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
# Keep the case-format task a physical, portable snapshot for the factory.
cp -R harbor/medusa-oversell-v2/{task.toml,instruction.md,steps,tests,solution,responder,environment} cases/medusa-oversell-v2/harbor/medusa-oversell-v2/
# Use host-cached runtime images so every fresh verifier can start without Docker Hub blobs.
cache=$(mktemp -d /tmp/unbug-v2-runtime-images.XXXXXX)
trap 'rm -rf "$cache"' EXIT
for image in postgres:17.11-bookworm redis:7.4.8-bookworm node:22.22.2-bookworm-slim python:3.12-slim; do
  docker image inspect "$image" >/dev/null 2>&1 || docker pull "$image"
done
# Install the exact lock once on the host; every nested build still verifies it and builds source.
deps="unbug-bench-medusa-deps:$(shasum -a 256 projects/medusa/package-lock.json | cut -d ' ' -f 1)"
docker build -f projects/medusa/Dockerfile.deps -t "$deps" projects/medusa
printf '%s\n' "$deps" > "$cache/medusa-deps-image"
docker save -o "$cache/runtime-images.tar" postgres:17.11-bookworm redis:7.4.8-bookworm node:22.22.2-bookworm-slim python:3.12-slim "$deps"
for target in box judge; do
  docker build --build-context "runtime_images=$cache" -f harbor/medusa-oversell-v2/Dockerfile --target "$target" -t "unbug-bench-$target:v2-dev" .
done
