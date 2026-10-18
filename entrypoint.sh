#!/bin/bash
set -euo pipefail

wait_for_db() {
  if [[ -z "${DATABASE_URL:-}" ]]; then
    echo "DATABASE_URL not set; skipping DB wait."
    return
  fi
  python - <<'PY'
import os, sys, time
from sqlalchemy import create_engine, text

engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
for attempt in range(1, 31):
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("Database ready.")
        break
    except Exception as exc:
        print(f"Waiting for database ({attempt}/30): {type(exc).__name__}")
        time.sleep(2)
else:
    sys.exit("Database never became available.")
PY
}

wait_for_db

echo "Applying database migrations..."
flask db upgrade

flask bootstrap-admin

echo "Starting Votilio..."
exec "$@"
