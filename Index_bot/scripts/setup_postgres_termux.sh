#!/data/data/com.termux/files/usr/bin/bash
# Native PostgreSQL on Termux (no Docker). Run once on the phone server.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PGDATA="${PGDATA:-$PREFIX/var/lib/postgresql}"
PG_USER="${INDEX_PG_USER:-index_user}"
PG_PASS="${INDEX_PG_PASS:-index_bot_local}"
PG_DB="${INDEX_PG_DB:-index_bot}"

echo "==> Installing PostgreSQL (Termux package, not Docker)"
pkg install -y postgresql

if [[ ! -d "$PGDATA" ]] || [[ ! -f "$PGDATA/PG_VERSION" ]]; then
  echo "==> Initializing cluster at $PGDATA"
  mkdir -p "$PGDATA"
  initdb -D "$PGDATA" --locale=C -E UTF8
fi

if ! pg_ctl -D "$PGDATA" status >/dev/null 2>&1; then
  echo "==> Starting PostgreSQL"
  pg_ctl -D "$PGDATA" -l "$PGDATA/logfile" start
  sleep 2
fi

echo "==> Creating role and database (ignore errors if they already exist)"
psql -d postgres -v ON_ERROR_STOP=0 <<SQL
CREATE USER ${PG_USER} WITH PASSWORD '${PG_PASS}';
CREATE DATABASE ${PG_DB} OWNER ${PG_USER};
GRANT ALL PRIVILEGES ON DATABASE ${PG_DB} TO ${PG_USER};
SQL

ENC_PASS="$(python3 -c "import urllib.parse; print(urllib.parse.quote('''${PG_PASS}''', safe=''))")"
URL="postgresql+psycopg://${PG_USER}:${ENC_PASS}@localhost:5432/${PG_DB}"

echo ""
echo "Add to .env (bot AND portal use the same DATABASE_URL):"
echo "DATABASE_URL=${URL}"
echo ""
echo "Then stop bot + portal, migrate data, and restart:"
echo "  ./stop_bot.sh"
echo "  # stop portal if running"
echo "  source venv/bin/activate"
echo "  pip install 'psycopg[binary]>=3.1'"
echo "  python scripts/migrate_sqlite_to_postgres.py"
echo ""
echo "Optional: start Postgres on boot — add to ~/.termux/boot/:"
echo "  pg_ctl -D \"${PGDATA}\" -l \"${PGDATA}/logfile\" start"
