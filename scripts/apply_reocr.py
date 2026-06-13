"""apply_reocr.py — Apply re-OCR JSON artifact to the database (#3, #4).

Runs anywhere (including the production container) — needs NO images and NO
Tesseract, only the JSON produced by scripts/reocr_export.py. Matches songs by
TITLE (production IDs do not align with the local DB where re-OCR ran),
replaces their lyrics, sets needs_review, and invalidates embeddings.

Usage:
    # Preview: per-song diff of stored vs re-OCR'd lyrics. Writes NOTHING.
    python scripts/apply_reocr.py scripts/reocr_export.json --dry-run

    # Apply: replace lyrics + flag review + invalidate embeddings.
    python scripts/apply_reocr.py scripts/reocr_export.json --apply

After --apply, re-index in the Web UI (Definições -> Re-indexar). Then review
the flagged songs (those needing manual fixes).

ALWAYS --dry-run first and confirm a database backup (Phase 0).
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


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
    return "\n".join(
        difflib.unified_diff(
            old.splitlines(), new.splitlines(),
            fromfile=f"{title} (stored)", tofile=f"{title} (re-OCR)", lineterm="",
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply a re-OCR JSON artifact to the DB.")
    parser.add_argument("artifact", help="Path to the reocr_export.json file")
    parser.add_argument("--db", default=None, help="Path to the SQLite database")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Show diffs only; write nothing.")
    mode.add_argument("--apply", action="store_true", help="Replace lyrics, flag review, invalidate embeddings.")
    args = parser.parse_args()

    artifact = Path(args.artifact)
    if not artifact.exists():
        print(f"ERROR: artifact not found: {artifact}")
        sys.exit(1)
    entries = json.loads(artifact.read_text(encoding="utf-8"))

    db_path = _resolve_db_path(args.db)
    if not Path(db_path).exists():
        print(f"ERROR: database not found: {db_path}")
        sys.exit(1)
    print(f"Database: {db_path}")
    print(f"Artifact: {artifact} ({len(entries)} songs)")
    print(f"Mode: {'DRY RUN (no writes)' if args.dry_run else 'APPLY'}\n")

    from cncsearch.ingest.clean import clean_lyrics

    # Fail fast on a malformed artifact rather than crashing mid-apply with a
    # partially-written DB.
    for i, entry in enumerate(entries):
        if "title" not in entry or "new_lyrics" not in entry:
            missing = {"title", "new_lyrics"} - set(entry)
            print(f"ERROR: entry {i} missing keys {missing}")
            sys.exit(1)

    changed = applied = not_found = unchanged = 0

    if args.dry_run:
        # Read existing lyrics with plain SQL so the dry-run works on ANY schema
        # (the needs_review column may not exist yet) and writes nothing. Match
        # by Python lower() (Unicode-aware) to mirror the apply path exactly —
        # SQLite COLLATE NOCASE folds only ASCII, missing accented titles.
        import sqlite3

        con = sqlite3.connect(db_path)
        try:
            # Only Resucito ('caminho') rows, to mirror the source-scoped apply
            # path — a shared title in 'paroquia' must not shadow the match.
            stored = {
                t.strip().lower(): lyr
                for t, lyr in con.execute(
                    "SELECT title, lyrics FROM canticos WHERE source = ?", ("caminho",)
                ).fetchall()
            }
        finally:
            con.close()
        for entry in entries:
            title = entry["title"]
            cleaned_new = clean_lyrics(entry["new_lyrics"].strip())
            needs_review = bool(entry.get("needs_review", False))
            old = stored.get(title.strip().lower())
            if old is None:
                not_found += 1
                print(f"  NOT FOUND: {title!r}")
                continue
            if cleaned_new == old:
                unchanged += 1
                continue
            changed += 1
            print(_diff(title, old, cleaned_new))
            print(f"  [needs_review={needs_review}]\n")
    else:
        from cncsearch.database.repository import Repository

        repo = Repository(db_path)
        repo.init_database()  # ensure needs_review column exists
        for entry in entries:
            title = entry["title"]
            needs_review = bool(entry.get("needs_review", False))
            existing = repo.get_cantico_by_title(title, source="caminho")
            if existing is None:
                not_found += 1
                print(f"  NOT FOUND: {title!r}")
                continue
            cleaned_new = clean_lyrics(entry["new_lyrics"].strip())
            if cleaned_new == existing.lyrics:
                unchanged += 1
                continue
            changed += 1
            # Re-OCR'd sheets are all Resucito imports (source='caminho'); scope
            # the match so a shared title never overwrites a 'paroquia' song.
            result = repo.reocr_replace_by_title(
                title, entry["new_lyrics"], needs_review, source="caminho"
            )
            if result is not None:
                applied += 1

    print("-" * 60)
    if args.dry_run:
        print(
            f"DRY RUN: {changed} would change, {unchanged} already match, "
            f"{not_found} not found in DB. Nothing written."
        )
    else:
        print(
            f"APPLIED: {applied}/{changed} songs re-OCR'd (embeddings invalidated), "
            f"{unchanged} unchanged, {not_found} not found."
        )
        print(
            "\nNext: re-index in the Web UI (Definições -> Re-indexar todos os "
            "cânticos), then review the flagged songs."
        )


if __name__ == "__main__":
    main()
