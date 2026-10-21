"""Additive, non-destructive schema migration.

`Base.metadata.create_all` only creates MISSING TABLES; it never adds columns to a table
that already exists. This module therefore:
  1. creates missing tables,
  2. adds missing columns (always as NULL-able / with defaults) to existing tables,
  3. adds the new unique constraints where the existing data allows it,
  4. back-fills the new columns from existing rows.
It never drops, renames or truncates anything and is safe to run repeatedly.
"""
import logging

from sqlalchemy import inspect, text

from app.database.connection import Base
from app.database import models  # noqa: F401  (registers tables)

logger = logging.getLogger("synuser.migrate")

UNIQUE_INDEXES = [
    ("survey_responses", "uq_response_question_persona", ["question_id", "persona_id"]),
    ("interview_messages", "uq_message_session_sequence", ["session_id", "sequence_number"]),
    ("survey_participants", "uq_participant_survey_persona", ["survey_id", "persona_id"]),
]


def _add_missing_columns(conn, inspector) -> list[str]:
    added = []
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            col_type = column.type.compile(dialect=conn.dialect)
            conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {column.name} {col_type} NULL"))
            added.append(f"{table.name}.{column.name}")
    return added


def _add_unique_indexes(engine) -> list[str]:
    """Each index gets its own connection: MySQL DDL auto-commits, so SAVEPOINTs cannot wrap it."""
    warnings = []
    for table, name, cols in UNIQUE_INDEXES:
        with engine.connect() as conn:
            inspector = inspect(conn)
            if not inspector.has_table(table):
                continue
            have = {i["name"] for i in inspector.get_indexes(table)} | {
                u["name"] for u in inspector.get_unique_constraints(table)}
            if name in have:
                continue
            try:
                conn.execute(text(f"CREATE UNIQUE INDEX {name} ON {table} ({', '.join(cols)})"))
                conn.commit()
            except Exception as exc:  # existing duplicate rows etc. -> leave data alone, tell the user
                conn.rollback()
                reason = str(getattr(exc, "orig", exc))[:160]
                msg = (f"Could not add unique index {name} on {table} ({reason}). "
                       "Remove the duplicate rows and restart to retry.")
                logger.warning(msg)
                warnings.append(msg)
    return warnings


def _backfill(conn) -> None:
    conn.execute(text(
        "UPDATE survey_experiments SET status='completed' WHERE status IS NULL AND id IN ("
        "SELECT DISTINCT q.survey_id FROM survey_questions q "
        "JOIN survey_responses r ON r.question_id = q.id)"))
    conn.execute(text("UPDATE survey_experiments SET status='draft' WHERE status IS NULL"))
    conn.execute(text(
        "INSERT INTO survey_participants (survey_id, persona_id) "
        "SELECT DISTINCT q.survey_id, r.persona_id FROM survey_responses r "
        "JOIN survey_questions q ON q.id = r.question_id "
        "WHERE NOT EXISTS (SELECT 1 FROM survey_participants p "
        "WHERE p.survey_id = q.survey_id AND p.persona_id = r.persona_id)"))
    # number legacy interview messages in the order they were stored
    sessions = conn.execute(text(
        "SELECT DISTINCT session_id FROM interview_messages WHERE sequence_number IS NULL")).fetchall()
    for (sid,) in sessions:
        start = conn.execute(text(
            "SELECT COALESCE(MAX(sequence_number),0) FROM interview_messages WHERE session_id=:s"),
            {"s": sid}).scalar()
        ids = conn.execute(text(
            "SELECT id FROM interview_messages WHERE session_id=:s AND sequence_number IS NULL ORDER BY id"),
            {"s": sid}).fetchall()
        for offset, (mid,) in enumerate(ids, start=1):
            conn.execute(text("UPDATE interview_messages SET sequence_number=:n WHERE id=:i"),
                         {"n": start + offset, "i": mid})
    conn.execute(text("UPDATE interview_sessions SET status='active' WHERE status IS NULL"))


def run_migrations(engine) -> dict:
    """Returns {"added_columns": [...], "warnings": [...]}"""
    Base.metadata.create_all(bind=engine)               # missing tables only
    with engine.begin() as conn:
        inspector = inspect(conn)
        added = _add_missing_columns(conn, inspector)
        _backfill(conn)
    warnings = _add_unique_indexes(engine)
    if added:
        logger.info("Added columns: %s", ", ".join(added))
    return {"added_columns": added, "warnings": warnings}
