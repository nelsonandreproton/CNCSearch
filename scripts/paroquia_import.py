"""Import parish canticos from a Word (.docx) document into CNCSearch.

The document structure uses:
  - Style 'Subttulo' (Subtítulo) → song title
  - All following non-empty paragraphs until the next Subttulo → lyrics

Usage:
    python scripts/paroquia_import.py path/to/livro.docx
    python scripts/paroquia_import.py path/to/livro.docx --db data/cncsearch.db
    python scripts/paroquia_import.py path/to/livro.docx --dry-run
    python scripts/paroquia_import.py path/to/livro.docx --limit 10
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Allow running from repo root or scripts/ directory
_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root))


def parse_docx(docx_path: Path) -> list[dict]:
    """Parse the Word document and return a list of {title, lyrics} dicts."""
    try:
        from docx import Document
    except ImportError:
        print("ERROR: python-docx not installed. Run: pip install python-docx")
        sys.exit(1)

    doc = Document(str(docx_path))
    songs: list[dict] = []
    current_title: str | None = None
    current_lyrics: list[str] = []

    for para in doc.paragraphs:
        style_name = para.style.name if para.style else ""
        text = para.text.strip()

        # Detect song title: style contains 'Subttulo' or 'Subtítulo'
        is_title = "Subttulo" in style_name or "Subt" in style_name

        if is_title and text:
            # Save previous song if any
            if current_title:
                lyrics = "\n".join(current_lyrics).strip()
                if lyrics:
                    songs.append({"title": current_title, "lyrics": lyrics})
            current_title = text
            current_lyrics = []
        elif current_title and text:
            current_lyrics.append(text)

    # Save last song
    if current_title:
        lyrics = "\n".join(current_lyrics).strip()
        if lyrics:
            songs.append({"title": current_title, "lyrics": lyrics})

    return songs


def main() -> None:
    parser = argparse.ArgumentParser(description="Import parish canticos from a .docx file")
    parser.add_argument("docx", help="Path to the .docx file")
    parser.add_argument("--db", default=None, help="Path to the SQLite database")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, do not write to DB")
    parser.add_argument("--limit", type=int, default=None, help="Import only first N songs")
    args = parser.parse_args()

    docx_path = Path(args.docx)
    if not docx_path.exists():
        print(f"ERROR: File not found: {docx_path}")
        sys.exit(1)

    # Resolve DB path
    if args.db:
        db_path = args.db
    else:
        from dotenv import load_dotenv
        load_dotenv(_repo_root / ".env")
        db_path = os.environ.get("DATABASE_PATH", str(_repo_root / "data" / "cncsearch.db"))

    print(f"Parsing: {docx_path}")
    songs = parse_docx(docx_path)
    print(f"Found {len(songs)} songs in document")

    if args.limit:
        songs = songs[: args.limit]
        print(f"Limited to first {args.limit} songs")

    if args.dry_run:
        print("\nDRY RUN — not writing to database\n")
        for i, s in enumerate(songs[:10], 1):
            print(f"{i}. {s['title']}")
            print(f"   Lyrics preview: {s['lyrics'][:80].replace(chr(10), ' ')}...")
        if len(songs) > 10:
            print(f"   ... and {len(songs) - 10} more")
        return

    # Import into database
    from cncsearch.database.repository import Repository

    repo = Repository(db_path)
    repo.init_database()

    imported = 0
    skipped = 0
    failed = 0

    for song in songs:
        title = song["title"]
        lyrics = song["lyrics"]

        # Skip duplicates (same title AND same source)
        existing = repo.get_cantico_by_title(title, source="paroquia")
        if existing:
            print(f"  SKIP (duplicate): {title}")
            skipped += 1
            continue

        try:
            repo.create_cantico(
                title=title,
                lyrics=lyrics,
                sheet_url=None,
                moment_ids=None,
                source="paroquia",
            )
            print(f"  OK: {title}")
            imported += 1
        except Exception as exc:
            print(f"  FAIL: {title} — {exc}")
            failed += 1

    print(f"\nResults: {imported} imported, {skipped} skipped, {failed} failed (total {len(songs)})")

    if imported > 0:
        print("\nNext step: generate embeddings for the new canticos.")
        print("Run via the web UI: Settings > Re-indexar todos os canticos")
        print("Or via script:")
        print("  python scripts/reindex.py  (if it exists)")


if __name__ == "__main__":
    main()
