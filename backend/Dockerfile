FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY requirements-dev.txt requirements.txt ./
RUN pip wheel --wheel-dir /wheels -r requirements-dev.txt

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/home/app/.local/bin:$PATH
RUN groupadd --system app && useradd --system --gid app --create-home app \
    && mkdir -p /home/app/.config/fuel-intelligence \
    && chmod 700 /home/app/.config/fuel-intelligence \
    && chown -R app:app /home/app/.config
WORKDIR /app
COPY --from=builder /wheels /wheels
COPY requirements-dev.txt requirements.txt ./
RUN pip install --no-index --find-links=/wheels -r requirements-dev.txt && rm -rf /wheels
COPY alembic.ini pyproject.toml entrypoint.sh ./
COPY alembic ./alembic
COPY app ./app
COPY tests ./tests
RUN chmod +x /app/entrypoint.sh && chown -R app:app /app
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
