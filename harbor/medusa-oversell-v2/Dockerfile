# Reuse the local v1 toolchain images; refresh bench code and isolate all v2 answers.
FROM unbug-bench-box:dev AS box
RUN apt-get update && apt-get install -y --no-install-recommends docker-buildx-plugin \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=runtime_images runtime-images.tar /opt/runtime-images.tar
COPY --from=runtime_images medusa-deps-image /opt/medusa-deps-image
COPY harbor/medusa-oversell-v2/environment/start-dockerd.sh /usr/local/bin/start-dockerd
COPY CONTESTANT.md ./
COPY factory/case_permissions.py factory/
COPY bin/bench_judging.py bin/bench.py bin/setup bin/reset bin/check bin/land bin/shoppers bin/
COPY projects/medusa projects/medusa
COPY projects/marketplace/service.py projects/marketplace/compose.yaml projects/marketplace/Dockerfile projects/marketplace/
COPY harbor/medusa-oversell-v2/environment/marketplace-README.md projects/marketplace/README.md
COPY harbor/medusa-oversell-v2/environment/marketplace-adapter.py projects/marketplace/adapter.py
COPY cases/medusa-oversell-v2/contestant.md CONTESTANT.md
COPY harbor/medusa-oversell-v2/environment/reset.py bin/reset
COPY harbor/medusa-oversell-v2/environment/sync-pending.py bin/sync-pending

FROM unbug-bench-judge:dev AS judge
# The v1 image lacks buildx; legacy nested builds copy the large npm layer repeatedly.
RUN apt-get update && apt-get install -y --no-install-recommends docker-buildx-plugin \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /bench
COPY --from=runtime_images runtime-images.tar /opt/runtime-images.tar
COPY --from=runtime_images medusa-deps-image /opt/medusa-deps-image
COPY harbor/medusa-oversell-v2/environment/start-dockerd.sh /usr/local/bin/start-dockerd
COPY bin bin
COPY factory factory
COPY projects projects
COPY cases cases
COPY tests tests
COPY scenarios/dev scenarios/dev
COPY guards guards
COPY harbor/medusa-oversell-v2/tests/test.sh /tests/test.sh
COPY harbor/medusa-oversell-v2/tests/pending.py /tests/pending.py
COPY harbor/medusa-oversell-v2/tests/case-root.json /tests/case-root.json
