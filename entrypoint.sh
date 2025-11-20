#!/bin/bash
set -euo pipefail

function wait_for_db() {
  if [[ -z "${DATABASE_URL:-}" ]]; then
    echo "DATABASE_URL not set; skipping DB wait."
    return
  fi
  python <<'PY'
import os, time
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

url = os.environ.get("DATABASE_URL")
engine = create_engine(url, pool_pre_ping=True)
for attempt in range(30):
    try:
        with engine.connect():
            print("Database connection established.")
            break
    except OperationalError as exc:
        wait = 2
        print(f"Database unavailable ({exc}); retrying in {wait}s...")
        time.sleep(wait)
else:
    raise SystemExit("Database never became available.")
PY
}

wait_for_db

echo "Applying database migrations..."
flask db upgrade

echo "Starting application..."
exec "$@"
