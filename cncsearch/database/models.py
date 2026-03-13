"""SQLAlchemy ORM models."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Moment(Base):
    """Liturgical moment (e.g. Entrada, Comunhão, Final)."""

    __tablename__ = "moments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    canticos = relationship("Cantico", back_populates="moment")

    def __repr__(self) -> str:
        return f"<Moment name={self.name!r}>"


class Cantico(Base):
    """A hymn with lyrics, optional sheet music URL and liturgical moment."""

    __tablename__ = "canticos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False, index=True)
    lyrics = Column(Text, nullable=False)
    sheet_url = Column(String(500), nullable=True)
    moment_id = Column(Integer, ForeignKey("moments.id"), nullable=True, index=True)
    embedding = Column(LargeBinary, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    moment = relationship("Moment", back_populates="canticos")

    def __repr__(self) -> str:
        return f"<Cantico id={self.id} title={self.title!r}>"


class Setting(Base):
    """Key-value store for application settings."""

    __tablename__ = "settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    def __repr__(self) -> str:
        return f"<Setting {self.key!r}={self.value!r}>"
