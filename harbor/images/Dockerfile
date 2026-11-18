# Two images for the Harbor spike, built from the bench root by harbor/build.sh.
#   box   - the contestant's container: Docker engine + the contestant bundle at /app
#   judge - the separate verifier: Docker engine + the whole bench at /bench + /tests/test.sh
FROM node:22.22.2-bookworm-slim AS base
# ponytail: Docker CE and apt packages unpinned; pin versions (and record digests) before freeze.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git python3 procps \
 && install -m 0755 -d /etc/apt/keyrings \
 && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
 && echo "deb [signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" \
      > /etc/apt/sources.list.d/docker.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends docker-ce docker-ce-cli containerd.io docker-compose-plugin \
 && rm -rf /var/lib/apt/lists/*
COPY harbor/images/start-dockerd.sh /usr/local/bin/start-dockerd

FROM base AS box
WORKDIR /app
COPY harbor/responder/ask-human /usr/local/bin/ask-human
RUN chmod +x /usr/local/bin/ask-human
# Contestant B's advanced tools (decided 2026-10-15): property-based and mutation testing.
# In every box so environments match; only B's prompt names them (Unbug may use them too).
RUN mkdir -p /opt/tools && cd /opt/tools && npm init -y >/dev/null \
 && npm install --no-audit --no-fund fast-check@4.10.2 @stryker-mutator/core@10.0.0 \
 && ln -s /opt/tools/node_modules/.bin/stryker /usr/local/bin/stryker
# ASSUMPTION: the contestant bundle. CONTESTANT.md tells contestants to run bin/setup and
# bin/reset; bench.py's reset reads the checker SQL, so it ships too. Traffic, probes,
# scenarios, keys and the reference guard do not. Confirm this list with the bench agent.
COPY CONTESTANT.md ./
COPY projects/medusa projects/medusa
COPY factory/case_permissions.py factory/
COPY bin/bench_judging.py bin/bench.py bin/processes.py bin/setup bin/reset bin/check bin/land bin/shoppers bin/
COPY cases/medusa-oversell/checker/check.sql cases/medusa-oversell/checker/
# bin/setup resets with the empty `none` guard (plain Medusa).
RUN mkdir -p guards/none

FROM base AS judge
WORKDIR /bench
COPY . .
COPY harbor/medusa-oversell/tests/test.sh /tests/test.sh
