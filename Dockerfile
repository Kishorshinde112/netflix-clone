FROM node:22-bookworm-slim AS frontend
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY index.html vite.config.js ./
COPY src ./src
COPY public ./public
COPY scripts ./scripts
RUN npm run build
FROM python:3.12-slim
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./
COPY --from=frontend /app/dist /app/dist
RUN mkdir -p /app/data && useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser
ENV PYTHONUNBUFFERED=1 COOKIE_SECURE=true
CMD ["sh", "-c", "exec uvicorn personal_server:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --workers 1"]
