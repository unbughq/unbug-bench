FROM node:22.22.2-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates git python3 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
