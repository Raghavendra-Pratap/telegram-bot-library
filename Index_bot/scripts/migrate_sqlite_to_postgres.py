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


def _sqlite_col_abs_max(src: Engine, table_name: str, col_name: str) -> int:
    """Return max(abs(value)) for one SQLite column; non-numeric/empty => 0."""
    q = text(
        f'SELECT MAX(ABS(CAST("{col_name}" AS INTEGER))) AS m '
        f'FROM "{table_name}" WHERE "{col_name}" IS NOT NULL'
    )
    with src.connect() as conn:
        v = conn.execute(q).scalar()
    try:
        return int(v or 0)
    except Exception:
        return 0


def _prepare_postgres_schema(src: Engine, dst: Engine) -> None:
    """Widen Postgres int columns to BIGINT when SQLite data exceeds int32."""
    if dst.dialect.name != "postgresql":
        return
    INT32_MAX = 2_147_483_647
    insp = inspect(dst)
    tables = set(insp.get_table_names())
    with dst.begin() as conn:
        for table in Base.metadata.sorted_tables:
            tname = table.name
            if tname not in tables:
                continue
            for col in table.columns:
                if str(col.type).upper() != "INTEGER":
                    continue
                abs_max = _sqlite_col_abs_max(src, tname, col.name)
                if abs_max <= INT32_MAX:
                    continue
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
                    {"table_name": tname, "column_name": col.name},
                ).scalar()
                if dtype in ("integer", "smallint"):
                    conn.execute(
                        text(
                            f'ALTER TABLE public."{tname}" '
                            f'ALTER COLUMN "{col.name}" TYPE BIGINT'
                        )
                    )
                    print(f"  widened {tname}.{col.name} to BIGINT (abs_max={abs_max})")


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
    _prepare_postgres_schema(src, dst)
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
