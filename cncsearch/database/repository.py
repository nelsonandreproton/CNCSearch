"""Database repository — all read/write operations."""

from __future__ import annotations

import csv
import io
import logging
from datetime import UTC, datetime

from sqlalchemy import create_engine, text
from sqlalchemy.orm import selectinload, sessionmaker

from .models import Base, Cantico, Moment, Setting, cantico_moments

logger = logging.getLogger(__name__)

_SETTING_DEFAULTS = {
    "top_n": "3",
    "min_similarity": "0.40",
    "web_username": "admin",
    "web_password_hash": "",  # set on first run from WEB_INITIAL_PASSWORD
}


class Repository:
    def __init__(self, db_path: str) -> None:
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
        )
        self.Session = sessionmaker(self.engine)

    def init_database(self, initial_password_hash: str = "") -> None:
        Base.metadata.create_all(self.engine)
        self._migrate_v2_moments()
        self._migrate_v3_source()
        self._seed_defaults(initial_password_hash)

    def _migrate_v2_moments(self) -> None:
        """Migrate from legacy single moment_id FK to cantico_moments association table."""
        with self.engine.begin() as conn:
            # Check if old moment_id column still exists on canticos
            pragma = conn.execute(text("PRAGMA table_info(canticos)")).fetchall()
            col_names = [row[1] for row in pragma]
            if "moment_id" not in col_names:
                return  # Already on new schema or fresh install

            # Avoid re-migration if table already has data
            existing = conn.execute(text("SELECT count(*) FROM cantico_moments")).scalar()
            if existing:
                return

            rows = conn.execute(
                text("SELECT id, moment_id FROM canticos WHERE moment_id IS NOT NULL")
            ).fetchall()
            for cantico_id, moment_id in rows:
                conn.execute(
                    text(
                        "INSERT OR IGNORE INTO cantico_moments (cantico_id, moment_id) "
                        "VALUES (:cid, :mid)"
                    ),
                    {"cid": cantico_id, "mid": moment_id},
                )
            logger.info("Migrated %d cantico moment associations to cantico_moments", len(rows))

    def _migrate_v3_source(self) -> None:
        """Add source column to canticos if it doesn't exist yet."""
        with self.engine.begin() as conn:
            pragma = conn.execute(text("PRAGMA table_info(canticos)")).fetchall()
            col_names = [row[1] for row in pragma]
            if "source" not in col_names:
                conn.execute(text("ALTER TABLE canticos ADD COLUMN source TEXT NOT NULL DEFAULT 'caminho'"))
                logger.info("Migrated canticos table: added source column (default='caminho')")

    def _seed_defaults(self, initial_password_hash: str) -> None:
        with self.Session() as s:
            for key, value in _SETTING_DEFAULTS.items():
                if s.get(Setting, key) is None:
                    if key == "web_password_hash" and initial_password_hash:
                        value = initial_password_hash
                    s.add(Setting(key=key, value=value))
            s.commit()

    # ── Settings ──────────────────────────────────────────────────────────────

    def get_setting(self, key: str, default: str = "") -> str:
        with self.Session() as s:
            row = s.get(Setting, key)
            return row.value if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.Session() as s:
            row = s.get(Setting, key)
            if row:
                row.value = value
                row.updated_at = datetime.now(UTC)
            else:
                s.add(Setting(key=key, value=value))
            s.commit()

    def get_all_settings(self) -> dict[str, str]:
        with self.Session() as s:
            return {r.key: r.value for r in s.query(Setting).all()}

    # ── Moments ───────────────────────────────────────────────────────────────

    def get_moments(self) -> list[Moment]:
        with self.Session() as s:
            rows = s.query(Moment).order_by(Moment.name).all()
            s.expunge_all()
            return rows

    def get_moment(self, moment_id: int) -> Moment | None:
        with self.Session() as s:
            row = s.get(Moment, moment_id)
            if row:
                s.expunge(row)
            return row

    def get_moment_by_name(self, name: str) -> Moment | None:
        with self.Session() as s:
            row = (
                s.query(Moment)
                .filter(Moment.name.ilike(name))
                .first()
            )
            if row:
                s.expunge(row)
            return row

    def create_moment(self, name: str) -> Moment:
        with self.Session() as s:
            m = Moment(name=name.strip())
            s.add(m)
            s.commit()
            s.refresh(m)
            s.expunge(m)
            return m

    def update_moment(self, moment_id: int, name: str) -> bool:
        with self.Session() as s:
            row = s.get(Moment, moment_id)
            if not row:
                return False
            row.name = name.strip()
            s.commit()
            return True

    def delete_moment(self, moment_id: int) -> bool:
        with self.Session() as s:
            row = s.get(Moment, moment_id)
            if not row:
                return False
            s.delete(row)
            s.commit()
            return True

    def count_canticos_for_moment(self, moment_id: int) -> int:
        with self.Session() as s:
            return (
                s.query(Cantico)
                .filter(Cantico.moments.any(Moment.id == moment_id))
                .count()
            )

    # ── Canticos ──────────────────────────────────────────────────────────────

    def get_cantico_by_title(self, title: str, source: str | None = None) -> Cantico | None:
        with self.Session() as s:
            q = s.query(Cantico).filter(Cantico.title.ilike(title))
            if source is not None:
                q = q.filter(Cantico.source == source)
            row = q.first()
            if row:
                s.expunge(row)
            return row

    def get_canticos(self, source: str | None = None) -> list[Cantico]:
        with self.Session() as s:
            q = (
                s.query(Cantico)
                .options(selectinload(Cantico.moments))
                .order_by(Cantico.title)
            )
            if source is not None:
                q = q.filter(Cantico.source == source)
            rows = q.all()
            s.expunge_all()
            return rows

    def get_cantico(self, cantico_id: int) -> Cantico | None:
        with self.Session() as s:
            row = (
                s.query(Cantico)
                .options(selectinload(Cantico.moments))
                .filter(Cantico.id == cantico_id)
                .first()
            )
            if row:
                s.expunge_all()
            return row

    def create_cantico(
        self,
        title: str,
        lyrics: str,
        sheet_url: str | None,
        moment_ids: list[int] | None = None,
        source: str = "caminho",
    ) -> Cantico:
        with self.Session() as s:
            c = Cantico(
                title=title.strip(),
                lyrics=lyrics.strip(),
                sheet_url=sheet_url.strip() if sheet_url else None,
                source=source,
            )
            if moment_ids:
                c.moments = [
                    m for mid in moment_ids
                    if (m := s.get(Moment, mid)) is not None
                ]
            s.add(c)
            s.commit()
            s.refresh(c)
            # Eager-load moments before expunge
            _ = [m.name for m in c.moments]
            s.expunge_all()
            return c

    def update_cantico(
        self,
        cantico_id: int,
        title: str,
        lyrics: str,
        sheet_url: str | None,
        moment_ids: list[int] | None = None,
    ) -> bool:
        with self.Session() as s:
            row = s.get(Cantico, cantico_id)
            if not row:
                return False
            row.title = title.strip()
            row.lyrics = lyrics.strip()
            row.sheet_url = sheet_url.strip() if sheet_url else None
            row.moments = [
                m for mid in (moment_ids or [])
                if (m := s.get(Moment, mid)) is not None
            ]
            row.updated_at = datetime.now(UTC)
            row.embedding = None  # invalidate — caller must re-embed
            s.commit()
            return True

    def delete_cantico(self, cantico_id: int) -> bool:
        with self.Session() as s:
            row = s.get(Cantico, cantico_id)
            if not row:
                return False
            s.delete(row)
            s.commit()
            return True

    def update_embedding(self, cantico_id: int, embedding_blob: bytes) -> None:
        with self.Session() as s:
            row = s.get(Cantico, cantico_id)
            if row:
                row.embedding = embedding_blob
                s.commit()

    def get_all_for_search(
        self, source: str | None = None
    ) -> list[tuple[int, str, str | None, list[int], bytes | None]]:
        """Return (id, title, sheet_url, moment_ids, embedding_blob) for canticos.

        If source is provided, only return canticos with that source value.
        """
        with self.Session() as s:
            q = s.query(Cantico).options(selectinload(Cantico.moments))
            if source is not None:
                q = q.filter(Cantico.source == source)
            rows = q.all()
            return [
                (c.id, c.title, c.sheet_url, [m.id for m in c.moments], c.embedding)
                for c in rows
            ]

    def count_canticos(self) -> int:
        with self.Session() as s:
            return s.query(Cantico).count()

    def count_canticos_without_embedding(self) -> int:
        with self.Session() as s:
            return (
                s.query(Cantico)
                .filter(Cantico.embedding.is_(None))
                .count()
            )

    # ── CSV Import ────────────────────────────────────────────────────────────

    def import_csv(self, content: str) -> dict:
        """
        Import hymns from CSV text.

        Expected columns: title, lyrics, sheet_url (opt), moment (opt)
        The moment column can contain multiple moment names separated by '|'.
        Auto-detects tab, semicolon, or comma delimiter from the header row.
        Returns {"imported": N, "errors": [{"row": N, "error": "..."}]}
        """
        imported = 0
        errors = []
        first_line = content.split("\n")[0]
        if "\t" in first_line:
            delimiter = "\t"
        elif ";" in first_line:
            delimiter = ";"
        else:
            delimiter = ","
        reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)

        for i, row in enumerate(reader, start=2):  # row 1 = header
            title = (row.get("title") or "").strip()
            lyrics = (row.get("lyrics") or "").strip()

            if not title or not lyrics:
                errors.append({"row": i, "error": "title e lyrics são obrigatórios"})
                continue

            sheet_url = (row.get("sheet_url") or "").strip() or None

            # Support multiple moment names separated by '|'
            moment_names = [
                n.strip()
                for n in (row.get("moment") or "").split("|")
                if n.strip()
            ]
            moment_ids: list[int] = []
            for moment_name in moment_names:
                m = self.get_moment_by_name(moment_name)
                if not m:
                    m = self.create_moment(moment_name)
                moment_ids.append(m.id)

            # Skip duplicates (case-insensitive title match)
            if self.get_cantico_by_title(title):
                errors.append({"row": i, "error": f"já existe um cântico com o título '{title}'"})
                continue

            # Replace escaped \n with actual newlines
            lyrics = lyrics.replace("\\n", "\n")

            self.create_cantico(title, lyrics, sheet_url, moment_ids or None)
            imported += 1

        return {"imported": imported, "errors": errors}
