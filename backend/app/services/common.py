"""Shared helpers for building prompts and loading project-scoped resources."""
from datetime import timedelta

from sqlalchemy.orm import Session

from app.database.models import (
    InterviewSession, Persona, Project, SurveyExperiment, utcnow,
)
from app.errors import NotFound

DISCLAIMER = ("AI-generated synthetic research. Personas and responses are simulated by a language model; "
              "they are not genuine customer feedback or statistically representative market research.")


def get_project_or_404(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise NotFound("Project not found")
    return project


def get_persona_or_404(db: Session, persona_id: int) -> Persona:
    persona = db.get(Persona, persona_id)
    if not persona:
        raise NotFound("Persona not found")
    return persona


def get_survey_or_404(db: Session, survey_id: int) -> SurveyExperiment:
    survey = db.get(SurveyExperiment, survey_id)
    if not survey:
        raise NotFound("Survey not found")
    return survey


def get_interview_or_404(db: Session, interview_id: int) -> InterviewSession:
    session = db.get(InterviewSession, interview_id)
    if not session:
        raise NotFound("Interview not found")
    return session


def persona_profile_text(p: Persona) -> str:
    rows = [("Name", p.name), ("Age", p.age), ("Occupation", p.occupation),
            ("Monthly income", f"{float(p.income):,.0f}" if p.income is not None else None),
            ("Location", p.location), ("Experience level", p.experience_level),
            ("Personality", p.personality), ("Goals", p.goals), ("Preferences", p.preferences),
            ("Pain points", p.pain_points), ("Research interests", p.research_interests)]
    lines = [f"{k}: {v}" for k, v in rows if v not in (None, "")]
    if p.behavior:
        scores = {k: getattr(p.behavior, k) for k in
                  ("expense_tracking", "saving_habit", "shopping_frequency", "impulse_buying",
                   "budget_awareness", "technology_usage") if getattr(p.behavior, k) is not None}
        if scores:
            lines.append("Behaviour scores (1-5): " + ", ".join(f"{k}={v}" for k, v in scores.items()))
    return "\n".join(lines)


def project_context_text(project: Project) -> str:
    rows = [("Project", project.name), ("Product / description", project.product_description),
            ("Target audience", project.target_market), ("Research objective", project.research_objective)]
    return "\n".join(f"{k}: {v}" for k, v in rows if v)


def is_stale(started_at, minutes: int) -> bool:
    return started_at is None or utcnow() - started_at > timedelta(minutes=minutes)
