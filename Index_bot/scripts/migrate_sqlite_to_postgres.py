#!/usr/bin/env python3
"""
Copy all rows from SQLite (DB_PATH) into PostgreSQL (DATABASE_URL).

Stop the bot and portal before running. Idempotent-ish: re-run only on empty
Postgres or you may get duplicate-key errors.

  cd Index_bot
  source venv/bin/activate
  export DATABASE_URL=postgresql+psycopg://...
  python scripts/migrate_sqlite_to_postgres.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env")

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import Engine

from config import Config
from database import Base


def _prepare_postgres_schema(dst: Engine) -> None:
    """Adjust integer width for known large-value columns before copy."""
    if dst.dialect.name != "postgresql":
        return
    widen: dict[str, tuple[str, ...]] = {
        "file_uploads": ("file_size", "message_id", "watch_message_id"),
        "upload_job_items": ("file_size", "telegram_message_id"),
    }
    with dst.begin() as conn:
        for table, cols in widen.items():
            for col in cols:
                dtype = conn.execute(
                    text(
                        """
                        SELECT data_type
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = :table_name
                          AND column_name = :column_name
                        """
                    ),
                    {"table_name": table, "column_name": col},
                ).scalar()
                if dtype in ("integer", "smallint"):
                    conn.execute(
                        text(f"ALTER TABLE public.{table} ALTER COLUMN {col} TYPE BIGINT")
                    )


def _sqlite_url() -> str:
    path = Path(Config.DB_PATH)
    if not path.is_absolute():
        path = _ROOT / path
    if not path.is_file():
        raise SystemExit(f"SQLite database not found: {path}")
    return f"sqlite:///{path}"


def _pg_url() -> str:
    url = (Config.DATABASE_URL or os.getenv("DATABASE_URL", "")).strip()
    if not url or "postgresql" not in url.lower():
        raise SystemExit(
            "Set DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/index_bot in .env"
        )
    return url


def _copy_tables(src: Engine, dst: Engine) -> None:
    Base.metadata.create_all(dst)
    _prepare_postgres_schema(dst)
    insp_dst = inspect(dst)
    existing = set(insp_dst.get_table_names())

    with src.connect() as sconn, dst.connect() as dconn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing:
                print(f"  skip {table.name} (not in destination schema)")
                continue
            rows = sconn.execute(select(table)).mappings().all()
            if not rows:
                print(f"  {table.name}: 0 rows")
                continue
            dconn.execute(table.delete())
            dconn.execute(table.insert(), [dict(r) for r in rows])
            dconn.commit()
            print(f"  {table.name}: {len(rows)} rows")

        for table in Base.metadata.sorted_tables:
            if "id" not in table.c:
                continue
            seq = dconn.execute(
                text(
                    "SELECT pg_get_serial_sequence(:tbl, 'id')"
                ),
                {"tbl": table.name},
            ).scalar()
            if not seq:
                continue
            dconn.execute(
                text(
                    f"SELECT setval(:seq, COALESCE((SELECT MAX(id) FROM {table.name}), 1), true)"
                ),
                {"seq": seq},
            )
        dconn.commit()


def main() -> int:
    src_url = _sqlite_url()
    dst_url = _pg_url()
    print(f"Source:  {src_url}")
    print(f"Target:  {dst_url.split('@')[-1]}")
    print("Copying tables…")

    src = create_engine(src_url)
    dst = create_engine(dst_url)
    _copy_tables(src, dst)

    print("\nDone. Set DATABASE_URL in .env for bot and portal, then restart both.")
    print("Keep index_bot.db as backup until you confirm everything works.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
