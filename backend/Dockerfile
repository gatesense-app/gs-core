FROM python:3.12-slim

WORKDIR /app

# psycopg2-binary ships a wheel, so no compiler toolchain is needed here.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
# Ship the migration config so `alembic upgrade head` can run from this image
# (e.g. as a Railway release command), not only from a checkout in CI.
COPY alembic.ini ./alembic.ini

# Documented default; the platform overrides it via $PORT below.
EXPOSE 8000

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    APP_ENV=production

# Railway (like most PaaS) injects the port to bind as $PORT. Binding a
# hardcoded 8000 would leave the container unreachable behind their proxy, so
# default the variable and expand it through a shell.
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
