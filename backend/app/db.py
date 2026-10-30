"""Database: user accounts, login sessions and saved trips.

SQLAlchemy 2.x, SQLite by default (a single file in backend/data/, which git
ignores). Point DATABASE_URL at PostgreSQL to use a server database instead,
e.g. postgresql+psycopg://user:pass@host/wayfinder (install psycopg first).
Tables are created on startup.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from .config import get_settings


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    # Empty for accounts created with Google that haven't set a password.
    password_hash: Mapped[str] = mapped_column(String(255))
    avatar_url: Mapped[str] = mapped_column(String(500), default="")
    name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str] = mapped_column(String(20), default="")
    home_city: Mapped[str] = mapped_column(String(80), default="")
    # Travel preferences, used to pre-fill the trip form.
    persona: Mapped[str] = mapped_column(String(16), default="budget")
    budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    diets: Mapped[list[str]] = mapped_column(JSON, default=list)
    interests: Mapped[list[str]] = mapped_column(JSON, default=list)
    bio: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    sessions: Mapped[list[LoginSession]] = relationship(back_populates="user", cascade="all, delete-orphan")
    trips: Mapped[list[Trip]] = relationship(back_populates="user", cascade="all, delete-orphan")
    oauth_accounts: Mapped[list[OAuthAccount]] = relationship(back_populates="user", cascade="all, delete-orphan")


class OAuthAccount(Base):
    """A sign-in identity from an outside provider (Google), linked to one Wayfinder user.

    `subject` is the provider's permanent user id (Google's "sub"); emails can change, ids don't.
    """

    __tablename__ = "oauth_accounts"
    __table_args__ = (UniqueConstraint("provider", "subject"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(254))
    name: Mapped[str] = mapped_column(String(120), default="")
    picture: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="oauth_accounts")


class LoginSession(Base):
    """A signed-in browser. Only a SHA-256 of the cookie token is stored."""

    __tablename__ = "login_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="sessions")


class Trip(Base):
    """A planned itinerary, saved automatically for signed-in users (one row per planning session)."""

    __tablename__ = "trips"
    __table_args__ = (UniqueConstraint("user_id", "session_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200))
    destination: Mapped[str] = mapped_column(String(120))
    start_date: Mapped[str] = mapped_column(String(10))
    end_date: Mapped[str] = mapped_column(String(10))
    persona: Mapped[str] = mapped_column(String(16))
    total: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    itinerary: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="trips")


class Visit(Base):
    """One page view. Visitors get a random ID cookie; signed-in customers are also linked to
    their account. The IP is stored with its last part hidden (e.g. 49.36.12.x)."""

    __tablename__ = "visits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    visitor_id: Mapped[str] = mapped_column(String(32), index=True)
    # Kept (as anonymous) if the customer later deletes their account.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    path: Mapped[str] = mapped_column(String(300))
    referrer: Mapped[str] = mapped_column(String(300), default="")
    browser: Mapped[str] = mapped_column(String(40), default="")
    os: Mapped[str] = mapped_column(String(40), default="")
    device: Mapped[str] = mapped_column(String(20), default="")
    ip_masked: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


def normalize_db_url(url: str) -> str:
    """Hosted Postgres (Neon, Render, Supabase) hands out postgres:// or postgresql:// URLs; use psycopg 3."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def _make_engine():
    url = get_settings().database_url
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(conn, _record):  # enforce ON DELETE CASCADE; WAL suits concurrent reads
            cur = conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

        return engine
    return create_engine(normalize_db_url(url), pool_pre_ping=True, pool_recycle=300)


engine = _make_engine()
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)  # creates missing tables (e.g. oauth_accounts) but not missing columns
    _add_missing_columns()


def _add_missing_columns() -> None:
    """Tiny migration for databases created before a column existed."""
    added = {"users": {"avatar_url": "VARCHAR(500) NOT NULL DEFAULT ''"}}
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, cols in added.items():
            have = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols.items():
                if name not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


@contextmanager
def db_session() -> Iterator[Session]:
    with SessionLocal() as s:
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
