"""Upgrade a database created by the ORIGINAL project schema without losing data."""
from sqlalchemy import create_engine, inspect, text

from app.database.migrate import run_migrations

LEGACY_DDL = [
    "CREATE TABLE projects (id INTEGER PRIMARY KEY, name VARCHAR(255) NOT NULL, product_description TEXT, target_market TEXT, research_objective TEXT)",
    "CREATE TABLE personas (id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), name VARCHAR(100) NOT NULL, age INTEGER, occupation VARCHAR(100), income DECIMAL(10,2), personality TEXT, goals TEXT, preferences TEXT, pain_points TEXT)",
    "CREATE TABLE behavior_profiles (id INTEGER PRIMARY KEY, persona_id INTEGER NOT NULL UNIQUE REFERENCES personas(id), expense_tracking INTEGER, saving_habit INTEGER, shopping_frequency INTEGER, impulse_buying INTEGER, budget_awareness INTEGER, technology_usage INTEGER)",
    "CREATE TABLE survey_experiments (id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), title VARCHAR(255) NOT NULL, description TEXT)",
    "CREATE TABLE survey_questions (id INTEGER PRIMARY KEY, survey_id INTEGER NOT NULL REFERENCES survey_experiments(id), question_text TEXT NOT NULL, question_type VARCHAR(50) NOT NULL, question_order INTEGER NOT NULL)",
    "CREATE TABLE survey_responses (id INTEGER PRIMARY KEY, question_id INTEGER NOT NULL REFERENCES survey_questions(id), persona_id INTEGER NOT NULL REFERENCES personas(id), response_text TEXT NOT NULL)",
    "CREATE TABLE interview_sessions (id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), persona_id INTEGER NOT NULL REFERENCES personas(id), title VARCHAR(255) NOT NULL, status VARCHAR(50) NOT NULL)",
    "CREATE TABLE interview_messages (id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES interview_sessions(id), role VARCHAR(20) NOT NULL, message_text TEXT NOT NULL)",
]
LEGACY_DATA = [
    "INSERT INTO projects VALUES (1,'Old project','desc','market','objective')",
    "INSERT INTO personas (id,project_id,name,age,occupation,income,goals) VALUES (1,1,'Old Persona',30,'Teacher',25000,'save')",
    "INSERT INTO personas (id,project_id,name,age,occupation,income,goals) VALUES (2,1,'Second',40,'Doctor',90000,'invest')",
    "INSERT INTO survey_experiments VALUES (1,1,'Old survey','d')",
    "INSERT INTO survey_experiments VALUES (2,1,'Empty survey','d')",
    "INSERT INTO survey_questions VALUES (1,1,'Old question?','open_ended',1)",
    "INSERT INTO survey_responses VALUES (1,1,1,'old answer 1')",
    "INSERT INTO survey_responses VALUES (2,1,2,'old answer 2')",
    "INSERT INTO interview_sessions VALUES (1,1,1,'Old interview','active')",
    "INSERT INTO interview_messages VALUES (1,1,'researcher','old q')",
    "INSERT INTO interview_messages VALUES (2,1,'persona','old a')",
]


def test_legacy_database_is_upgraded_in_place(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as c:
        for stmt in LEGACY_DDL + LEGACY_DATA:
            c.execute(text(stmt))

    result = run_migrations(engine)
    assert "projects.category" in result["added_columns"] and "survey_experiments.status" in result["added_columns"]
    assert result["warnings"] == []

    cols = {c["name"] for c in inspect(engine).get_columns("interview_messages")}
    assert {"sequence_number", "created_at"} <= cols
    assert inspect(engine).has_table("survey_participants") and inspect(engine).has_table("reports")

    with engine.connect() as c:
        assert c.execute(text("SELECT name FROM projects")).scalar() == "Old project"
        assert c.execute(text("SELECT COUNT(*) FROM survey_responses")).scalar() == 2         # data preserved
        assert c.execute(text("SELECT response_text FROM survey_responses WHERE id=2")).scalar() == "old answer 2"
        statuses = dict(c.execute(text("SELECT id, status FROM survey_experiments")).fetchall())
        assert statuses == {1: "completed", 2: "draft"}                                       # back-filled
        parts = {tuple(r) for r in c.execute(text("SELECT survey_id, persona_id FROM survey_participants"))}
        assert parts == {(1, 1), (1, 2)}
        seq = [r[0] for r in c.execute(text("SELECT sequence_number FROM interview_messages ORDER BY id"))]
        assert seq == [1, 2]

    again = run_migrations(engine)                                                            # idempotent
    assert again["added_columns"] == [] and again["warnings"] == []
    with engine.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM survey_participants")).scalar() == 2


def test_duplicate_legacy_rows_do_not_break_migration(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'dups.db'}")
    with engine.begin() as c:
        for stmt in LEGACY_DDL + LEGACY_DATA:
            c.execute(text(stmt))
        c.execute(text("INSERT INTO survey_responses VALUES (3,1,1,'duplicate answer')"))
    result = run_migrations(engine)
    assert any("uq_response_question_persona" in w for w in result["warnings"])               # reported, data untouched
    with engine.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM survey_responses")).scalar() == 3
