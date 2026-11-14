# Behave Kyndryl: one image with the website, the API, the mission engine and the Payment API sandbox.
# Built in the cloud by `az acr build` (deploy/azure/deploy.sh) or by GitHub Actions.

# ---- 1. Build the React website ------------------------------------------------
FROM node:24-slim AS web
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY index.html tsconfig*.json vite.config.ts ./
COPY public ./public
COPY src ./src
RUN npm run build

# ---- 2. Python runtime -----------------------------------------------------------
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY backend/requirements.txt backend-requirements.txt
COPY payment_api/requirements.txt payment-requirements.txt
RUN pip install -r backend-requirements.txt -r payment-requirements.txt

COPY backend ./backend
COPY payment_api ./payment_api
COPY sample_services ./sample_services
COPY projects.json ./
COPY --from=web /web/dist ./dist

# Run as an unprivileged user; data/ holds only the sandbox's throwaway files (the workspace lives in PostgreSQL).
RUN useradd --create-home --uid 10001 behave && mkdir -p /app/data && chown -R behave /app/data
USER behave

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)"
CMD ["python", "-m", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
