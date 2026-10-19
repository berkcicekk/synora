# syntax=docker/dockerfile:1
# Synora imajı. Kurulum: deploy/README.md ("Docker ile"). Önde TLS için nginx gerekir.

FROM python:3.12-slim-trixie AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Önce yalnızca bağımlılıklar: kod değişince bu katman önbellekten gelir.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim-trixie
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin synora \
    && mkdir /data && chown synora:synora /data && chmod 700 /data
COPY --from=build /app/.venv /app/.venv
COPY rulesets /app/rulesets
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SYNORA_DB_PATH=/data/synora.db \
    SYNORA_RULESETS_DIR=/app/rulesets
WORKDIR /app
USER synora
# Veritabanı her zaman ayrı bölümde: unutulsa bile kapsayıcı katmanına yazılmaz.
VOLUME /data
EXPOSE 8000
# /health veritabanı ya da iş yürütücü sorunluysa 503 döner (urlopen hata fırlatır).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]
CMD ["synora", "serve", "--host", "0.0.0.0", "--port", "8000"]
