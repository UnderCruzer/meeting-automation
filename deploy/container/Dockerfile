FROM node:20-bookworm-slim AS ui
WORKDIR /build
ENV NEXT_TELEMETRY_DISABLED=1
COPY recording-page/package.json recording-page/package-lock.json ./
RUN npm ci
COPY recording-page/ ./
RUN npm run build

FROM python:3.11-slim-bookworm
RUN useradd --create-home --uid 1000 workspace
COPY --from=ui /usr/local/bin/node /usr/local/bin/node
WORKDIR /app
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY --chown=workspace backend/app /app/backend/app
COPY --from=ui --chown=workspace /build/.next/standalone /app/frontend
COPY --from=ui --chown=workspace /build/.next/static /app/frontend/.next/static
COPY --from=ui --chown=workspace /build/public /app/frontend/public
COPY --chown=workspace deploy/container/start.py /app/start.py
RUN mkdir -p /app/data/recordings && chown -R workspace:workspace /app/data
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 WORKSPACE_MODE=standalone STORAGE_DIR=/app/data/recordings UPLOAD_API_URL=http://127.0.0.1:8000 WORKSPACE_STORAGE=ephemeral
USER workspace
EXPOSE 7860
CMD ["python", "/app/start.py"]
