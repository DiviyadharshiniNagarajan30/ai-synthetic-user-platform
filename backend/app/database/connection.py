"""SQLAlchemy engine/session setup.

The engine is created lazily-safe: importing this module never raises when the database
is unreachable, so the API can start and report a clear status via /health/database.
"""
import logging

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

from app import config

logger = logging.getLogger("synuser.db")
Base = declarative_base()


def _build_engine(url: str):
    if not url:
        return None
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url or url.rstrip("/") == "sqlite:":
            kwargs["poolclass"] = StaticPool
    else:
        kwargs["pool_recycle"] = 1800
        kwargs["connect_args"] = {"connect_timeout": 5}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):  # enforce FKs/cascades in SQLite like MySQL does
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    return engine


engine = _build_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine) if engine else None


def safe_database_label() -> str:
    """Connection target without the password, for logs and health output."""
    if not config.DATABASE_URL:
        return "(DATABASE_URL not set)"
    return make_url(config.DATABASE_URL).render_as_string(hide_password=True)


def get_db():
    if SessionLocal is None:
        from app.errors import ServiceUnavailable
        raise ServiceUnavailable(
            "DATABASE_URL is not configured. Copy .env.example to backend/.env and set it."
        )
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
