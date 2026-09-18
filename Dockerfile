# Single-image deploy: build the React SPA, then run FastAPI which serves both
# the API (/api/*) and the built SPA from the same origin (so the session
# cookie + CSRF same-origin check just work — no CORS to configure).

# ---- Stage 1: build the frontend bundle ----
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build   # -> /web/dist

# ---- Stage 2: python runtime ----
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DOSSLAP_HTTPS=1
WORKDIR /app/backend

# Install deps first for better layer caching.
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

# App code + the built SPA. main.py expects the bundle at <repo>/frontend/dist,
# i.e. one level above backend/ (FRONTEND_DIR = dirname(BACKEND_DIR)).
COPY backend/ /app/backend/
COPY --from=web /web/dist /app/frontend/dist

# Railway/most PaaS inject $PORT; default to 8000 for local `docker run`.
# --proxy-headers so the app sees the real https scheme + client IP behind the
# platform's TLS proxy (correct webhook URLs, secure cookies, login throttling).
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
