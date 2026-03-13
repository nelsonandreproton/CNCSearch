"""Database repository — all read/write operations."""

from __future__ import annotations

import csv
import io
import logging
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .models import Base, Cantico, Moment, Setting

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
        self._seed_defaults(initial_password_hash)

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
            # Unlink canticos first
            for c in s.query(Cantico).filter(Cantico.moment_id == moment_id).all():
                c.moment_id = None
            s.delete(row)
            s.commit()
            return True

    def count_canticos_for_moment(self, moment_id: int) -> int:
        with self.Session() as s:
            return s.query(Cantico).filter(Cantico.moment_id == moment_id).count()

    # ── Canticos ──────────────────────────────────────────────────────────────

    def get_canticos(self) -> list[Cantico]:
        with self.Session() as s:
            rows = (
                s.query(Cantico)
                .outerjoin(Moment)
                .order_by(Cantico.title)
                .all()
            )
            for r in rows:
                if r.moment:
                    _ = r.moment.name  # eager-load
            s.expunge_all()
            return rows

    def get_cantico(self, cantico_id: int) -> Cantico | None:
        with self.Session() as s:
            row = s.get(Cantico, cantico_id)
            if row:
                if row.moment:
                    _ = row.moment.name
                s.expunge_all()
            return row

    def create_cantico(
        self,
        title: str,
        lyrics: str,
        sheet_url: str | None,
        moment_id: int | None,
    ) -> Cantico:
        with self.Session() as s:
            c = Cantico(
                title=title.strip(),
                lyrics=lyrics.strip(),
                sheet_url=sheet_url.strip() if sheet_url else None,
                moment_id=moment_id,
            )
            s.add(c)
            s.commit()
            s.refresh(c)
            s.expunge(c)
            return c

    def update_cantico(
        self,
        cantico_id: int,
        title: str,
        lyrics: str,
        sheet_url: str | None,
        moment_id: int | None,
    ) -> bool:
        with self.Session() as s:
            row = s.get(Cantico, cantico_id)
            if not row:
                return False
            row.title = title.strip()
            row.lyrics = lyrics.strip()
            row.sheet_url = sheet_url.strip() if sheet_url else None
            row.moment_id = moment_id
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

    def get_all_for_search(self) -> list[tuple[int, str, str | None, int | None, bytes | None]]:
        """Return (id, title, sheet_url, moment_id, embedding_blob) for every cantico."""
        with self.Session() as s:
            rows = s.query(
                Cantico.id,
                Cantico.title,
                Cantico.sheet_url,
                Cantico.moment_id,
                Cantico.embedding,
            ).all()
            return list(rows)

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
        Returns {"imported": N, "errors": [{"row": N, "error": "..."}]}
        """
        imported = 0
        errors = []
        reader = csv.DictReader(io.StringIO(content))

        for i, row in enumerate(reader, start=2):  # row 1 = header
            title = (row.get("title") or "").strip()
            lyrics = (row.get("lyrics") or "").strip()

            if not title or not lyrics:
                errors.append({"row": i, "error": "title e lyrics são obrigatórios"})
                continue

            sheet_url = (row.get("sheet_url") or "").strip() or None
            moment_name = (row.get("moment") or "").strip()
            moment_id = None

            if moment_name:
                m = self.get_moment_by_name(moment_name)
                if not m:
                    m = self.create_moment(moment_name)
                moment_id = m.id

            # Replace escaped \n with actual newlines
            lyrics = lyrics.replace("\\n", "\n")

            self.create_cantico(title, lyrics, sheet_url, moment_id)
            imported += 1

        return {"imported": imported, "errors": errors}
