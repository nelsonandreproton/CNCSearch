"""Biblical reference detection and verse lookup.

Detects references like "João 3:16", "Mt 5:3-12", "Salmo 23" in a query
and expands them with the actual verse text so the embedding has richer
semantic context.

Uses bible-api.com with the Almeida translation (free, no key required).
"""

from __future__ import annotations

import logging
import re
import unicodedata

import httpx

logger = logging.getLogger(__name__)

# ── Normalisation ─────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    """Lowercase + strip accents for case/accent-insensitive lookup."""
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().lower().strip()


# ── Book name map: Portuguese name/abbrev → bible-api.com 3-letter code ──────
# All keys are already normalised (no accents, lowercase).

_BOOK_MAP: dict[str, str] = {
    # ── Old Testament ─────────────────────────────────────────────────────────
    "gn": "GEN",   "gen": "GEN",   "genesis": "GEN",
    "ex": "EXO",   "exodo": "EXO",
    "lv": "LEV",   "lev": "LEV",   "levitico": "LEV",
    "nm": "NUM",   "num": "NUM",   "numeros": "NUM",
    "dt": "DEU",   "deut": "DEU",  "deuteronomio": "DEU",
    "js": "JOS",   "jos": "JOS",   "josue": "JOS",
    "jz": "JDG",   "jui": "JDG",   "juizes": "JDG",
    "rt": "RUT",   "rute": "RUT",
    "1sm": "1SA",  "1sam": "1SA",  "1samuel": "1SA",
    "2sm": "2SA",  "2sam": "2SA",  "2samuel": "2SA",
    "1rs": "1KI",  "1rei": "1KI",  "1reis": "1KI",
    "2rs": "2KI",  "2rei": "2KI",  "2reis": "2KI",
    "1cr": "1CH",  "1cron": "1CH", "1cronicas": "1CH",
    "2cr": "2CH",  "2cron": "2CH", "2cronicas": "2CH",
    "esd": "EZR",  "esdras": "EZR",
    "ne": "NEH",   "nee": "NEH",   "neemias": "NEH",
    "est": "EST",  "ester": "EST",
    "jo": "JOB",   "job": "JOB",   "jo": "JOB",
    "sl": "PSA",   "sal": "PSA",   "salmo": "PSA",  "salmos": "PSA",
    "ps": "PSA",   "psl": "PSA",
    "pr": "PRO",   "prov": "PRO",  "proverbios": "PRO",
    "ec": "ECC",   "ecl": "ECC",   "eclesiastes": "ECC",
    "qo": "ECC",   "qoh": "ECC",
    "ct": "SNG",   "cant": "SNG",  "cantares": "SNG",
                   "cantico": "SNG", "canticos": "SNG",
    "is": "ISA",   "isa": "ISA",   "isaias": "ISA",
    "jr": "JER",   "jer": "JER",   "jeremias": "JER",
    "lm": "LAM",   "lam": "LAM",   "lamentacoes": "LAM",
    "ez": "EZK",   "ezq": "EZK",   "ezequiel": "EZK",
    "dn": "DAN",   "dan": "DAN",   "daniel": "DAN",
    "os": "HOS",   "ose": "HOS",   "oseias": "HOS",
    "jl": "JOL",   "joel": "JOL",
    "am": "AMO",   "amos": "AMO",
    "ab": "OBA",   "abd": "OBA",   "abdias": "OBA",
    "jn": "JON",   "jon": "JON",   "jonas": "JON",
    "mq": "MIC",   "mic": "MIC",   "miqueias": "MIC",
    "na": "NAM",   "nab": "NAM",   "naum": "NAM",
    "hab": "HAB",  "habacuc": "HAB",
    "sf": "ZEP",   "sof": "ZEP",   "sofonias": "ZEP",
    "ag": "HAG",   "ageu": "HAG",
    "zc": "ZEC",   "zac": "ZEC",   "zacarias": "ZEC",
    "ml": "MAL",   "mal": "MAL",   "malaquias": "MAL",

    # ── New Testament ─────────────────────────────────────────────────────────
    "mt": "MAT",   "mat": "MAT",   "mateus": "MAT",
    "mc": "MRK",   "mar": "MRK",   "marcos": "MRK",
    "lc": "LUK",   "luc": "LUK",   "lucas": "LUK",
    # João (John) — full name wins over "jo"=Job when user writes full name
    "joao": "JHN", "jao": "JHN",
    "at": "ACT",   "atos": "ACT",
    "rm": "ROM",   "rom": "ROM",   "romanos": "ROM",
    "1co": "1CO",  "1cor": "1CO",  "1corintios": "1CO",
    "2co": "2CO",  "2cor": "2CO",  "2corintios": "2CO",
    "gl": "GAL",   "gal": "GAL",   "galatas": "GAL",
    "ef": "EPH",   "efe": "EPH",   "efesios": "EPH",
    "fl": "PHP",   "fil": "PHP",   "filipenses": "PHP",
    "cl": "COL",   "col": "COL",   "colossenses": "COL",
    "1ts": "1TH",  "1tes": "1TH",  "1tessalonicenses": "1TH",
    "2ts": "2TH",  "2tes": "2TH",  "2tessalonicenses": "2TH",
    "1tm": "1TI",  "1tim": "1TI",  "1timoteo": "1TI",
    "2tm": "2TI",  "2tim": "2TI",  "2timoteo": "2TI",
    "tt": "TIT",   "tit": "TIT",   "tito": "TIT",
    "fm": "PHM",   "flm": "PHM",   "filemon": "PHM",
    "hb": "HEB",   "heb": "HEB",   "hebreus": "HEB",
    "tg": "JAS",   "jas": "JAS",   "tiago": "JAS",
    "1pe": "1PE",  "1pt": "1PE",   "1pedro": "1PE",
    "2pe": "2PE",  "2pt": "2PE",   "2pedro": "2PE",
    "1jo": "1JN",  "1jn": "1JN",   "1joao": "1JN",
    "2jo": "2JN",  "2jn": "2JN",   "2joao": "2JN",
    "3jo": "3JN",  "3jn": "3JN",   "3joao": "3JN",
    "jd": "JUD",   "jud": "JUD",   "judas": "JUD",
    "ap": "REV",   "apo": "REV",   "apocalipse": "REV",
}

# ── Regex ─────────────────────────────────────────────────────────────────────
# Matches: [1-3 ]<book> <chapter>[:<verse>[-<end>]]
# Accepts ":" or "," as chapter/verse separator (common in Portuguese bibles).

_REF_RE = re.compile(
    r"""^
    (?P<prefix>[123]\s+)?                             # optional "1 ", "2 ", "3 "
    (?P<book>[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\.]*)              # book name or abbreviation
    \s+
    (?P<chapter>\d+)
    (?:[,:](?P<verse>\d+)(?:-(?P<end_verse>\d+))?)?   # optional :verse[-end]
    $""",
    re.VERBOSE | re.IGNORECASE | re.UNICODE,
)

_VERSE_LIMIT = 600  # truncate very long passages (whole chapters) to this


def _resolve_book(raw: str) -> str | None:
    """Return the bible-api.com book code for a raw Portuguese string, or None."""
    key = _norm(raw)

    # Remove trailing dot (abbreviation marker)
    key = key.rstrip(".")

    # Handle numbered books that come through as e.g. "1cor" (prefix already merged)
    if key in _BOOK_MAP:
        return _BOOK_MAP[key]

    # Prefix match: "apocalipse" → starts with "apoc"
    for pt, code in _BOOK_MAP.items():
        if len(pt) >= 3 and key.startswith(pt):
            return code

    return None


def expand_query(query: str) -> str:
    """If query is a biblical reference, return 'query\\nverse text'. Else return query unchanged."""
    stripped = query.strip()
    m = _REF_RE.match(stripped)
    if not m:
        return query

    prefix = (m.group("prefix") or "").strip()
    book_raw = (prefix + m.group("book")).strip()
    code = _resolve_book(book_raw)
    if not code:
        logger.debug("Unknown biblical book: %r", book_raw)
        return query

    chapter = m.group("chapter")
    verse = m.group("verse")
    end_verse = m.group("end_verse")

    if verse:
        ref = f"{code}+{chapter}:{verse}"
        if end_verse:
            ref += f"-{end_verse}"
    else:
        ref = f"{code}+{chapter}"

    try:
        resp = httpx.get(
            f"https://bible-api.com/{ref}",
            params={"translation": "almeida"},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            logger.debug("Bible API error for %r: %s", ref, data["error"])
            return query
        verse_text = data.get("text", "").strip()
        if not verse_text:
            return query
        # Trim excessive whitespace / \xa0 from verse formatting
        verse_text = " ".join(verse_text.split())
        if len(verse_text) > _VERSE_LIMIT:
            verse_text = verse_text[:_VERSE_LIMIT].rsplit(" ", 1)[0] + "…"
        logger.debug("Expanded %r → %d chars of verse text", stripped, len(verse_text))
        return f"{stripped}\n{verse_text}"
    except Exception as exc:
        logger.debug("Bible lookup failed for %r: %s", ref, exc)
        return query
