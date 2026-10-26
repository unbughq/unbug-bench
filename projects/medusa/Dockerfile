ARG MEDUSA_DEPS_IMAGE=node:22.22.2-bookworm-slim
FROM ${MEDUSA_DEPS_IMAGE}
WORKDIR /app
# Public audit CA only, empty outside the logged contestant network.
ARG UNBUG_PROXY_CA=""
RUN if [ -n "$UNBUG_PROXY_CA" ]; then \
      printf '%s' "$UNBUG_PROXY_CA" | base64 -d > /tmp/unbug-webproxy.crt; \
    fi
ENV NODE_ENV=development MEDUSA_TELEMETRY_DISABLED=true NODE_OPTIONS=--max-old-space-size=1536
COPY package.json package-lock.json ./
COPY verify-lock.mjs ./
RUN node verify-lock.mjs
RUN if [ -s /tmp/unbug-webproxy.crt ]; then export NODE_EXTRA_CA_CERTS=/tmp/unbug-webproxy.crt; fi; \
    if [ -f /opt/medusa-deps.sha256 ]; then \
      sha256sum -c /opt/medusa-deps.sha256; \
    else npm ci --no-audit --no-fund; fi
COPY medusa-config.ts tsconfig.json ./
COPY src ./src
ENV MEDUSA_DISABLE_TELEMETRY=true
RUN npx medusa build
ENV NODE_ENV=production
CMD ["sh", "-c", "cd .medusa/server && npm start"]
