# syntax=docker/dockerfile:1

# ---- build the CSV editor bundle ----
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm test && npx vite build --outDir /out --emptyOutDir

# ---- runtime ----
FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FLASK_APP=wsgi.py \
    APP_ENV=production

RUN useradd --system --create-home --uid 10001 votilio
WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY --chown=votilio:votilio . .
COPY --from=frontend --chown=votilio:votilio /out ./app/static/dist
RUN mkdir -p app/static/uploads && chown -R votilio:votilio app/static/uploads && chmod +x entrypoint.sh

USER votilio
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"

ENTRYPOINT ["./entrypoint.sh"]
CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
