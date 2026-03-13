"""
resucito_import.py — Bulk import from https://app.resucito.es into CNCSearch.

Pipeline:
  1. Playwright: open the SPA, call the song-list function, get JSON with 225 PT songs
  2. Download each song's PNG image(s) from media.ressuscitou.pt
  3. OCR: mask red chord pixels, run pytesseract (por), clean text
  4. Create moments + canticos in the CNCSearch database (skips duplicates)

Usage:
  cd C:\\DEV\\CNCSearch
  python scripts/resucito_import.py [--db PATH] [--limit N] [--dry-run]

Prerequisites:
  pip install playwright pytesseract Pillow
  playwright install chromium
  # Tesseract-OCR with Portuguese language pack:
  # https://github.com/UB-Mannheim/tesseract/wiki
  # (also available via: winget install UB-Mannheim.TesseractOCR)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
import requests
from dotenv import load_dotenv
from PIL import Image
from playwright.sync_api import sync_playwright

# ── Optional pytesseract import ──────────────────────────────────────────────
try:
    import pytesseract

    # On Windows, tesseract is typically not in PATH — set it explicitly.
    _TESSERACT_WIN = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if sys.platform == "win32" and Path(_TESSERACT_WIN).exists():
        pytesseract.pytesseract.tesseract_cmd = _TESSERACT_WIN

    TESSERACT_OK = True
except ImportError:
    TESSERACT_OK = False

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
CACHE_DIR = Path(__file__).parent / "resucito_images"
SONG_LIST_CACHE = Path(__file__).parent / "resucito_songs.json"

# ── Tag → Moment name mapping ──────────────────────────────────────────────
TAG_TO_MOMENT: dict[str, str] = {
    # Liturgical colors
    "white":              "Branco",
    "blue":               "Azul",
    "green":              "Verde",
    # Functional moments
    "entrance":           "Entrada",
    "communion":          "Comunhão",
    "lauds":              "Laudes",
    "easter_pentecost":   "Páscoa - Pentecostes",
    "final":              "Final",
    "penitential":        "Penitencial",
    "fractionOfTheBread": "Fração do Pão",
    "peace":              "Paz",
    "advent":             "Advento",
    "christmas":          "Natal",
    "virgin":             "Virgem Maria",
    "acclamation":        "Aclamação",
    "psalmody":           "Salmodia",
    "liturgy":            "Liturgia",
}


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — Fetch song list
# ─────────────────────────────────────────────────────────────────────────────

def fetch_song_list(use_cache: bool = True) -> list[dict]:
    """Fetch the 225 Portuguese songs from resucito.es using Playwright.

    Caches the result to scripts/resucito_songs.json to avoid re-fetching.
    """
    if use_cache and SONG_LIST_CACHE.exists():
        logger.info("Loading song list from cache: %s", SONG_LIST_CACHE)
        return json.loads(SONG_LIST_CACHE.read_text(encoding="utf-8"))

    logger.info("Fetching song list from app.resucito.es via Playwright...")
    songs: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="pt-PT")
        page = context.new_page()

        # Set Portuguese locale via Capacitor storage BEFORE the app loads.
        # The app reads localStorage['CapacitorStorage.settings'].locale to pick the song list.
        page.goto("https://app.resucito.es", wait_until="domcontentloaded", timeout=30_000)
        page.evaluate("""
            () => {
                const settings = {theme: 'light', hapticsActive: false, keepAwake: false, locale: 'pt'};
                localStorage.setItem('CapacitorStorage.settings', JSON.stringify(settings));
            }
        """)
        # Navigate to a song page to trigger the full app initialisation with PT locale
        page.goto("https://app.resucito.es/canto/1", wait_until="networkidle", timeout=60_000)

        songs = page.evaluate("""
            async () => {
                // Find the current utils module URL from loaded scripts
                const scripts = Array.from(document.querySelectorAll('script[src]'))
                    .map(s => s.src);
                const utilsUrl = scripts.find(s => s.includes('SongService')) ||
                                 scripts.find(s => s.includes('utils-'));
                if (!utilsUrl) {
                    // Fallback: try known URL patterns
                    const candidates = [
                        '/assets/utils-CiHyOo8k.js',
                    ];
                    for (const url of candidates) {
                        try {
                            const mod = await import(url);
                            if (mod.g) {
                                const result = await mod.g();
                                const list = result?.list?.value ?? result;
                                if (Array.isArray(list) && list.length > 0) return list;
                            }
                        } catch (_) { /* try next */ }
                    }
                    return [];
                }

                // Try to find and call the song-list loader (exported as 'g')
                // It lives in the utils bundle, imported in SongDetailPage as 're'
                const utilsBundle = scripts.find(s => /utils-/.test(s));
                if (utilsBundle) {
                    const mod = await import(utilsBundle);
                    if (mod.g) {
                        const result = await mod.g();
                        const list = result?.list?.value ?? result;
                        if (Array.isArray(list)) return list;
                    }
                }

                // Last resort: try every loaded script for a function that returns songs
                for (const src of scripts) {
                    if (!src.includes('/assets/')) continue;
                    try {
                        const mod = await import(src);
                        for (const key of Object.keys(mod)) {
                            const fn = mod[key];
                            if (typeof fn !== 'function') continue;
                            try {
                                const r = await fn();
                                const list = r?.list?.value ?? r;
                                if (Array.isArray(list) && list.length > 50 && list[0]?.title) {
                                    return list;
                                }
                            } catch (_) { /* skip */ }
                        }
                    } catch (_) { /* skip */ }
                }
                return [];
            }
        """)
        browser.close()

    if not songs:
        raise RuntimeError(
            "Could not retrieve song list from resucito.es. "
            "The app may have been updated — check the assets URL."
        )

    logger.info("Fetched %d songs. Saving cache to %s", len(songs), SONG_LIST_CACHE)
    SONG_LIST_CACHE.write_text(
        json.dumps(songs, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return songs


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — Download images
# ─────────────────────────────────────────────────────────────────────────────

def download_image(url: str) -> Path:
    """Download a PNG from media.ressuscitou.pt, caching locally."""
    CACHE_DIR.mkdir(exist_ok=True)
    fname = CACHE_DIR / url.split("/")[-1]
    if fname.exists():
        return fname
    logger.debug("Downloading %s", url)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    fname.write_bytes(resp.content)
    return fname


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — OCR
# ─────────────────────────────────────────────────────────────────────────────

def ocr_image(img_path: Path) -> str:
    """OCR a song image, stripping red chord annotations first."""
    if not TESSERACT_OK:
        raise RuntimeError("pytesseract is not installed. Run: pip install pytesseract")

    img = Image.open(img_path).convert("RGB")
    arr = np.array(img)

    # Mask red pixels (chord annotations): R >> G and R >> B
    red_mask = (
        (arr[:, :, 0].astype(int) - arr[:, :, 1].astype(int) > 60)
        & (arr[:, :, 0].astype(int) - arr[:, :, 2].astype(int) > 60)
        & (arr[:, :, 0] > 120)
    )
    arr[red_mask] = [255, 255, 255]  # white out chords

    cleaned = Image.fromarray(arr)
    text: str = pytesseract.image_to_string(
        cleaned,
        lang="por",
        config="--psm 6 --oem 3",
    )

    # Clean up: collapse excessive blank lines, strip trailing whitespace
    lines = [line.rstrip() for line in text.splitlines()]
    deduped: list[str] = []
    blank_run = 0
    for line in lines:
        if line == "":
            blank_run += 1
            if blank_run <= 1:
                deduped.append(line)
        else:
            blank_run = 0
            deduped.append(line)

    return "\n".join(deduped).strip()


# ─────────────────────────────────────────────────────────────────────────────
# Step 4+5 — Import into CNCSearch
# ─────────────────────────────────────────────────────────────────────────────

def import_songs(
    songs: list[dict],
    db_path: str,
    dry_run: bool = False,
    limit: int | None = None,
) -> None:
    # Import CNCSearch repository (add project root to path)
    sys.path.insert(0, str(PROJECT_ROOT))
    from cncsearch.database.repository import Repository  # noqa: PLC0415

    repo = Repository(db_path)
    repo.init_database()

    if limit:
        songs = songs[:limit]

    total = len(songs)
    imported = skipped = failed = 0

    for i, song in enumerate(songs, start=1):
        title = song.get("title", "").strip()
        if not title:
            logger.warning("[%d/%d] Empty title — skipping", i, total)
            failed += 1
            continue

        prefix = f"[{i}/{total}] {title!r}"

        # Duplicate check
        if repo.get_cantico_by_title(title):
            logger.info("%s — SKIP (already exists)", prefix)
            skipped += 1
            continue

        # OCR all images
        lyrics_parts: list[str] = []
        img_urls: list[str] = song.get("img_urls", [])
        for url in img_urls:
            try:
                img_path = download_image(url)
                ocr_text = ocr_image(img_path)
                if ocr_text:
                    lyrics_parts.append(ocr_text)
            except Exception as exc:
                logger.warning("%s — OCR failed for %s: %s", prefix, url, exc)

        # Prepend subtitle if OCR yielded nothing (shouldn't happen, but safety net)
        lyrics = "\n\n".join(lyrics_parts)
        if not lyrics:
            subtitle = song.get("subtitle", "").strip()
            lyrics = subtitle or title
            logger.warning("%s — No OCR text, using subtitle as fallback", prefix)

        # Resolve moments (deduplicate: some songs have repeated tags)
        seen_moment_ids: set[int] = set()
        moment_ids: list[int] = []
        for tag in song.get("tags", []):
            moment_name = TAG_TO_MOMENT.get(tag)
            if not moment_name:
                continue
            if dry_run:
                continue
            m = repo.get_moment_by_name(moment_name) or repo.create_moment(moment_name)
            if m.id not in seen_moment_ids:
                seen_moment_ids.add(m.id)
                moment_ids.append(m.id)

        # sheet_url = first image (the song sheet with chords + lyrics)
        sheet_url = img_urls[0] if img_urls else None

        if dry_run:
            logger.info(
                "%s — DRY RUN: %d moments, %d chars lyrics, sheet=%s",
                prefix, len(song.get("tags", [])), len(lyrics), sheet_url,
            )
            imported += 1
            continue

        try:
            repo.create_cantico(title, lyrics, sheet_url, moment_ids or None)
            logger.info(
                "%s — IMPORTED (%d moments, %d chars)",
                prefix, len(moment_ids), len(lyrics),
            )
            imported += 1
        except Exception as exc:
            logger.error("%s — FAILED: %s", prefix, exc)
            failed += 1

        # Brief pause to avoid hammering media.ressuscitou.pt
        time.sleep(0.1)

    print(
        f"\n{'DRY RUN ' if dry_run else ''}Results: "
        f"{imported} imported, {skipped} skipped, {failed} failed"
        f" (total {total})"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")

    parser = argparse.ArgumentParser(description="Import songs from resucito.es into CNCSearch")
    parser.add_argument(
        "--db",
        default=None,
        help="Path to CNCSearch SQLite database (default: $DATABASE_PATH or ./data/cncsearch.db)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only import the first N songs (useful for testing)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run OCR and log what would be imported, but don't write to the database",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Force re-fetch of the song list even if resucito_songs.json exists",
    )
    args = parser.parse_args()

    import os
    db_path = args.db or os.environ.get("DATABASE_PATH", str(PROJECT_ROOT / "data" / "cncsearch.db"))
    logger.info("Database: %s", db_path)

    songs = fetch_song_list(use_cache=not args.no_cache)
    logger.info("Song list: %d songs", len(songs))

    import_songs(songs, db_path, dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    main()
