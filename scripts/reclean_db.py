"""reclean_db.py — Re-clean lyrics already stored in CNCSearch (#2).

Applies the shared cleaning module (cncsearch/ingest/clean.py) to every
cantico already in the database, WITHOUT reprocessing any images. This fixes
OCR noise (page numbers, stray symbols, blank-line runs) in songs that were
imported before the cleaning module existed.

Usage:
    # Preview every change as a unified diff — writes NOTHING to the DB:
    python scripts/reclean_db.py --dry-run

    # Apply the cleaning. Each changed row is re-saved via update_cantico,
    # which also invalidates its embedding (sets embedding = NULL), so a
    # subsequent "Re-indexar" in the Web UI regenerates them:
    python scripts/reclean_db.py --apply

After --apply, re-index in the Web UI: Definições -> "Re-indexar todos os
cânticos" (Definições should then show 0 cânticos sem embedding).

ALWAYS run --dry-run first and confirm you have a database backup (Phase 0).
"""

from __future__ import annotations

import argparse
import difflib
import os
import sys
from pathlib import Path

# Diffs may contain characters outside the Windows console's default codepage
# (accented Portuguese and U+FFFD from already-corrupted rows). Force UTF-8 so
# printing never raises UnicodeEncodeError.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Allow running from repo root or scripts/ directory.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cncsearch.ingest.clean import clean_lyrics  # noqa: E402


def _resolve_db_path(arg_db: str | None) -> str:
    if arg_db:
        return arg_db
    try:
        from dotenv import load_dotenv

        load_dotenv(_REPO_ROOT / ".env")
    except ImportError:
        pass
    return os.environ.get("DATABASE_PATH", str(_REPO_ROOT / "data" / "cncsearch.db"))


def _diff(title: str, old: str, new: str) -> str:
    lines = difflib.unified_diff(
        old.splitlines(),
        new.splitlines(),
        fromfile=f"{title} (before)",
        tofile=f"{title} (after)",
        lineterm="",
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-clean already-imported cantico lyrics (no image reprocessing)."
    )
    parser.add_argument("--db", default=None, help="Path to the SQLite database")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Show a diff for every cantico that would change. Writes nothing.",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Apply the cleaning to the database (invalidates embeddings of changed rows).",
    )
    args = parser.parse_args()

    db_path = _resolve_db_path(args.db)
    if not Path(db_path).exists():
        print(f"ERROR: database not found: {db_path}")
        sys.exit(1)
    print(f"Database: {db_path}")
    print(f"Mode: {'DRY RUN (no writes)' if args.dry_run else 'APPLY'}\n")

    from cncsearch.database.repository import Repository

    repo = Repository(db_path)
    # In dry-run we must not write anything — skip init_database() (which runs
    # additive migrations + seed inserts). Only --apply may touch the schema.
    if args.apply:
        repo.init_database()

    canticos = repo.get_canticos()
    changed = 0
    applied = 0

    for c in canticos:
        cleaned = clean_lyrics(c.lyrics)
        if cleaned == c.lyrics:
            continue
        changed += 1

        if args.dry_run:
            print(_diff(c.title, c.lyrics, cleaned))
            print()
        else:
            moment_ids = [m.id for m in c.moments]
            # update_cantico re-applies clean_lyrics (idempotent) and sets
            # embedding = NULL on the row.
            result = repo.update_cantico(
                c.id, c.title, c.lyrics, c.sheet_url, moment_ids or None
            )
            if result is not None:
                applied += 1

    print("-" * 60)
    if args.dry_run:
        print(
            f"DRY RUN: {changed} of {len(canticos)} cânticos would change. "
            "Nothing written. Re-run with --apply to save."
        )
    else:
        print(
            f"APPLIED: {applied} of {len(canticos)} cânticos re-cleaned "
            "(embeddings invalidated)."
        )
        print(
            "\nNext step: re-index in the Web UI — Definições -> "
            "'Re-indexar todos os cânticos'."
        )


if __name__ == "__main__":
    main()
