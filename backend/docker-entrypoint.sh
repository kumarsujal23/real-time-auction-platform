#!/usr/bin/env bash
set -euo pipefail

echo "Waiting for Postgres..."
python - << 'PYEOF'
import time
import sqlalchemy
from app.core.config import settings

for attempt in range(30):
    try:
        engine = sqlalchemy.create_engine(settings.SYNC_DATABASE_URL)
        with engine.connect():
            pass
        print("Postgres is up.")
        break
    except Exception as exc:  # noqa: BLE001
        print(f"Postgres not ready yet ({exc}); retrying...")
        time.sleep(1)
else:
    raise SystemExit("Postgres never became available")
PYEOF

echo "Running migrations..."
alembic upgrade head

case "${1:-api}" in
  api)
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000
    ;;
  worker)
    exec python -m app.workers.auction_worker
    ;;
  *)
    exec "$@"
    ;;
esac
