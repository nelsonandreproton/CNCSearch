"""SQLAlchemy ORM models."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, LargeBinary, String, Table, Text, text as sa_text
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# Many-to-many association table: a cantico can belong to multiple moments
cantico_moments = Table(
    "cantico_moments",
    Base.metadata,
    Column("cantico_id", Integer, ForeignKey("canticos.id", ondelete="CASCADE"), primary_key=True),
    Column("moment_id", Integer, ForeignKey("moments.id", ondelete="CASCADE"), primary_key=True),
)


class Moment(Base):
    """Liturgical moment (e.g. Entrada, Comunhão, Final)."""

    __tablename__ = "moments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    canticos = relationship("Cantico", secondary=cantico_moments, back_populates="moments")

    def __repr__(self) -> str:
        return f"<Moment name={self.name!r}>"


class Cantico(Base):
    """A hymn with lyrics, optional sheet music URL and liturgical moments."""

    __tablename__ = "canticos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False, index=True)
    lyrics = Column(Text, nullable=False)
    sheet_url = Column(String(500), nullable=True)
    source = Column(String(50), nullable=False, server_default="caminho")
    embedding = Column(LargeBinary, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    moments = relationship("Moment", secondary=cantico_moments, back_populates="canticos")

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
