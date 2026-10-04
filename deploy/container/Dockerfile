FROM node:24-bookworm-slim AS ui
WORKDIR /build
ENV NEXT_TELEMETRY_DISABLED=1
COPY recording-page/package.json recording-page/package-lock.json ./
RUN npm ci
COPY recording-page/ ./
RUN npm run build

FROM node:24-bookworm-slim AS bot
WORKDIR /bot
COPY slack-bot/package.json slack-bot/package-lock.json ./
RUN npm ci --omit=dev
COPY slack-bot/src ./src

FROM python:3.11-slim-bookworm AS litestream
# Optional continuous SQLite backup to S3-compatible storage (#85). Pinned and checksum-verified.
ARG TARGETARCH
ARG LITESTREAM_VERSION=0.5.17
ADD https://github.com/benbjohnson/litestream/releases/download/v${LITESTREAM_VERSION}/litestream-${LITESTREAM_VERSION}-linux-x86_64.tar.gz /tmp/litestream-amd64.tar.gz
ADD https://github.com/benbjohnson/litestream/releases/download/v${LITESTREAM_VERSION}/litestream-${LITESTREAM_VERSION}-linux-arm64.tar.gz /tmp/litestream-arm64.tar.gz
RUN echo "cfb371176d164437ae869f8351cfde49bd1804ae71c61923f75c9cba9c9c006d  /tmp/litestream-amd64.tar.gz" | sha256sum -c - \
 && echo "f8ca4a050095c1efbda2c4365172e61bf9d955ea0d9ac42f448b52e51819baa5  /tmp/litestream-arm64.tar.gz" | sha256sum -c - \
 && tar -xzf /tmp/litestream-${TARGETARCH:-amd64}.tar.gz -C /usr/local/bin litestream \
 && /usr/local/bin/litestream version

FROM python:3.11-slim-bookworm
RUN useradd --create-home --uid 1000 workspace
COPY --from=litestream /usr/local/bin/litestream /usr/local/bin/litestream
COPY --from=ui /usr/local/bin/node /usr/local/bin/node
WORKDIR /app
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY --chown=workspace backend/app /app/backend/app
COPY --from=ui --chown=workspace /build/.next/standalone /app/frontend
COPY --from=ui --chown=workspace /build/.next/static /app/frontend/.next/static
COPY --from=ui --chown=workspace /build/public /app/frontend/public
COPY --from=bot --chown=workspace /bot /app/slack-bot
COPY --chown=workspace deploy/container/start.py /app/start.py
RUN mkdir -p /app/data/recordings && chown -R workspace:workspace /app/data
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 WORKSPACE_MODE=standalone STORAGE_DIR=/app/data/recordings UPLOAD_API_URL=http://127.0.0.1:8000 WORKSPACE_STORAGE=ephemeral
USER workspace
EXPOSE 7860
CMD ["python", "/app/start.py"]
