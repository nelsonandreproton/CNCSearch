"""reocr_export.py — Column-aware re-OCR of Resucito sheets -> portable JSON (#3, #4).

Runs LOCALLY (needs Tesseract + the cached PNGs in scripts/resucito_images/,
neither of which exist in the production container). Emits a portable artifact
that scripts/apply_reocr.py imports into the production database WITHOUT needing
images or Tesseract there.

It writes NOTHING to any database. It only reads cached images and the song
list (scripts/resucito_songs.json) and produces a JSON file:

    [{"title", "new_lyrics", "columns", "mean_confidence", "needs_review"}, ...]

Usage:
    # All cached resucito sheets -> scripts/reocr_export.json
    python scripts/reocr_export.py

    # Test a few first; custom output path
    python scripts/reocr_export.py --limit 5 --out scripts/reocr_sample.json

    # Only sheets whose title matches a substring (case-insensitive)
    python scripts/reocr_export.py --title "sião"
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

# UTF-8 stdout so accented diffs never raise on the Windows console.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cncsearch.ingest.ocr import ocr_sheet  # noqa: E402

_IMAGES = Path(__file__).parent / "resucito_images"
_SONG_LIST = Path(__file__).parent / "resucito_songs.json"
_DEFAULT_OUT = Path(__file__).parent / "reocr_export.json"


def _image_path_for(img_urls: list[str]) -> Path | None:
    """Resolve the first cached image for a song, or None if not downloaded."""
    for url in img_urls:
        filename = url.split("/")[-1]
        if not filename:  # guard against empty/trailing-slash URLs
            continue
        candidate = _IMAGES / filename
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-OCR cached Resucito sheets into a portable JSON artifact."
    )
    parser.add_argument("--out", default=str(_DEFAULT_OUT), help="Output JSON path")
    parser.add_argument("--limit", type=int, default=None, help="Only process first N")
    parser.add_argument("--title", default=None, help="Only titles containing this substring")
    args = parser.parse_args()

    if not _SONG_LIST.exists():
        print(f"ERROR: song list not found: {_SONG_LIST}")
        sys.exit(1)

    from PIL import Image

    songs = json.loads(_SONG_LIST.read_text(encoding="utf-8"))
    if args.title:
        needle = args.title.lower()
        songs = [s for s in songs if needle in (s.get("title") or "").lower()]
    if args.limit:
        songs = songs[: args.limit]

    results: list[dict] = []
    no_image = skipped = flagged = 0

    for i, song in enumerate(songs, start=1):
        title = (song.get("title") or "").strip()
        if not title:
            continue
        img_path = _image_path_for(song.get("img_urls", []))
        if img_path is None:
            no_image += 1
            continue

        try:
            res = ocr_sheet(Image.open(img_path))
        except Exception as exc:  # noqa: BLE001
            print(f"[{i}/{len(songs)}] {title!r} — OCR FAILED: {exc}")
            skipped += 1
            continue

        if not res.lyrics.strip():
            skipped += 1
            continue

        results.append(
            {
                "title": title,
                "new_lyrics": res.lyrics,
                "columns": res.columns,
                "mean_confidence": res.mean_confidence,
                "needs_review": res.needs_review,
            }
        )
        if res.needs_review:
            flagged += 1
        print(
            f"[{i}/{len(songs)}] {title!r} — {res.columns}col "
            f"conf={res.mean_confidence} review={res.needs_review}"
        )

    out_path = Path(args.out)
    out_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("-" * 60)
    print(
        f"Exported {len(results)} songs to {out_path} "
        f"({flagged} flagged for review, {no_image} had no cached image, "
        f"{skipped} skipped)."
    )
    print(
        "\nNext: copy the JSON to the server and run apply_reocr.py there "
        "(dry-run first)."
    )


if __name__ == "__main__":
    main()
