FROM node:22.22.2-bookworm-slim AS node
FROM postgres:17.11-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends python3 \
 && rm -rf /var/lib/apt/lists/*
COPY --from=node /usr/local/bin/node /usr/local/bin/node
# No bench, case, key, guard or host volume enters this image.
ENTRYPOINT ["sleep", "infinity"]
