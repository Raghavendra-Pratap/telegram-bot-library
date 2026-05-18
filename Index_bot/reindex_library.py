#!/usr/bin/env python3
"""Re-parse and relink all indexed files to content_title (TMDB grouping)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env")

from database import Database, FileUpload
from media_utils import is_indexable_filename
from name_parser import NameParser
from title_indexer import build_index_metadata
from tmdb_helper import tmdb_helper


def main() -> int:
    db = Database()
    parser = NameParser()
    session = db.get_session()
    removed = updated = 0
    try:
        uploads = session.query(FileUpload).order_by(FileUpload.id).all()
        print(f"Reindexing {len(uploads)} file row(s)...")
        for upload in uploads:
            if not is_indexable_filename(upload.file_name):
                session.delete(upload)
                removed += 1
                continue
            meta = build_index_metadata(
                upload.file_name,
                parser=parser,
                tmdb_helper=tmdb_helper,
                db=db,
            )
            upload.parsed_name = meta["parsed_name"]
            upload.content_title_id = meta.get("content_title_id")
            upload.season_number = meta.get("season_number")
            upload.episode_number = meta.get("episode_number")
            upload.episode_title = meta.get("episode_title")
            upload.library_visible = bool(meta.get("library_visible"))
            if meta["auto_confirm"]:
                upload.is_confirmed = True
                upload.needs_confirmation = False
                upload.confirmed_name = meta["parsed_name"]
            elif meta.get("needs_tmdb_pick"):
                upload.is_confirmed = False
                upload.needs_confirmation = True
                upload.confirmed_name = None
                upload.library_visible = False
            updated += 1
            print(
                f"  #{upload.id} -> {meta['parsed_name'][:60]} "
                f"(content_title_id={meta.get('content_title_id')})"
            )
        session.commit()
        print(f"\nDone. Updated {updated}, removed {removed} subtitle row(s).")
        return 0
    except Exception as e:
        session.rollback()
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
