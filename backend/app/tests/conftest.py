import itertools
import json
import os

# Isolated in-memory DB by default. To run the suite against MySQL/MariaDB set TEST_DATABASE_URL to a
# DEDICATED database whose name contains "test" (the tests drop and recreate every table).
_url = os.getenv("TEST_DATABASE_URL", "sqlite://")
assert _url.startswith("sqlite") or "test" in _url.rsplit("/", 1)[-1], \
    "Refusing to run destructive tests: TEST_DATABASE_URL database name must contain 'test'"
os.environ["DATABASE_URL"] = _url
os.environ["OLLAMA_MAX_ATTEMPTS"] = "2"

import pytest
from fastapi.testclient import TestClient

from app.database import connection
from app.database.connection import Base
from app.database.migrate import run_migrations
from app.main import app
from app.services import ollama_service


GOALS = ["Retire early without debt", "Buy a first home within five years", "Fund a child's university degree",
         "Grow a small bakery's cash reserves", "Travel abroad every year", "Clear the education loan quickly"]
PAINS = ["Forgets recurring subscription renewals", "Irregular freelance income is hard to plan",
         "Receipts and invoices scattered everywhere", "Overspends on food delivery at month end",
         "Family expenses mixed with business costs", "Bank apps show confusing category labels"]


class FakeAI:
    """Stands in for the model at the lowest HTTP layer (`_chat`), so JSON parsing/validation still runs."""

    def __init__(self):
        self.counter = itertools.count(1)
        self.persona_overrides: list = []     # queue of raw strings to return for persona prompts
        self.fail_with: Exception | None = None
        self.fail_text_when: str | None = None  # substring of the user prompt that triggers failure
        self.calls: list[dict] = []

    def __call__(self, messages, *, json_mode, temperature, max_tokens):
        self.calls.append({"messages": messages, "json_mode": json_mode})
        if self.fail_with:
            raise self.fail_with
        user = messages[-1]["content"]
        if json_mode and "ONE fictional synthetic user persona" in user:
            if self.persona_overrides:
                return self.persona_overrides.pop(0)
            n = next(self.counter)
            return json.dumps({
                "name": f"Persona Number{n}", "age": 20 + n, "occupation": "Teacher", "income": f"{30000 + n}",
                "location": "Chennai", "experience_level": "intermediate",
                "personality": f"Curious and careful {n}", "goals": GOALS[n % len(GOALS)],
                "preferences": ["simple UI", "alerts"], "pain_points": PAINS[n % len(PAINS)],
                "research_interests": "budgeting",
                "behavior_scores": {k: 3 for k in ["expense_tracking", "saving_habit", "shopping_frequency",
                                                    "impulse_buying", "budget_awareness", "technology_usage"]}})
        if json_mode and "Summarise" in user:
            return json.dumps({"summary": "People want simpler tracking.", "themes": ["tracking", "alerts"],
                               "needs": ["clarity"], "preferences": ["simple"], "pain_points": ["manual entry"],
                               "recommendations": ["automate"]})
        if self.fail_text_when and self.fail_text_when in user:
            raise ollama_service.BadGateway("model failed for this item")
        return f"Simulated answer to: {user.splitlines()[-1][:60]}"


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch):
    Base.metadata.drop_all(bind=connection.engine)
    run_migrations(connection.engine)
    ai = FakeAI()
    monkeypatch.setattr(ollama_service, "_chat", ai)
    monkeypatch.setattr(ollama_service, "status", lambda: {
        "base_url": "x", "model": "m", "reachable": True, "model_installed": True, "installed_models": ["m"], "detail": "ok"})
    return ai


@pytest.fixture
def ai(fresh_db):
    return fresh_db


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def project(client):
    r = client.post("/projects/", json={"name": "Finance App", "product_description": "AI budgeting app",
                                        "target_market": "Everyone", "research_objective": "Find needs"})
    assert r.status_code == 201, r.text
    return r.json()


def make_persona(client, project_id, name="Arun Kumar", occupation="Software Engineer", **extra):
    r = client.post(f"/projects/{project_id}/personas",
                    json={"name": name, "age": 30, "occupation": occupation, "goals": "Save", "pain_points": "Subscriptions", **extra})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def personas(client, project):
    return [make_persona(client, project["id"], "Arun Kumar", "Software Engineer"),
            make_persona(client, project["id"], "Priya", "College Student"),
            make_persona(client, project["id"], "Meena", "Business Owner")]
