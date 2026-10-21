"""Project dashboard metrics. All numbers come from SQL; nothing is hardcoded."""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.models import (
    InterviewSession, Persona, PersonaGeneration, Report, SurveyExperiment,
)
from app.services import interview_service, survey_service


def statistics(db: Session, project_id: int) -> dict:
    def count(model, *conds):
        return db.query(func.count(model.id)).filter(model.project_id == project_id, *conds).scalar() or 0
    return {
        "project_id": project_id,
        "total_personas": count(Persona),
        "total_surveys": count(SurveyExperiment),
        "completed_surveys": count(SurveyExperiment, SurveyExperiment.status == "completed"),
        "total_interviews": count(InterviewSession),
        "completed_interviews": count(InterviewSession, InterviewSession.status == "completed"),
        "active_interviews": count(InterviewSession, InterviewSession.status == "active"),
        "persona_generations": count(PersonaGeneration),
        "reports_generated": count(Report),
        "definitions": {
            "completed_surveys": "Surveys whose status is 'completed' (every question answered by every selected persona).",
            "completed_interviews": "Interviews explicitly ended by the researcher.",
            "reports_generated": "PDF reports downloaded/generated for this project.",
        },
    }


def activity(db: Session, project_id: int, limit: int = 15) -> list[dict]:
    items = []
    for s in db.query(SurveyExperiment).filter_by(project_id=project_id).all():
        items.append({"type": "survey", "id": s.id, "title": s.title, "status": s.status or "draft",
                      "timestamp": s.completed_at or s.created_at})
    for i in db.query(InterviewSession).filter_by(project_id=project_id).all():
        items.append({"type": "interview", "id": i.id, "title": i.title, "status": i.status,
                      "timestamp": i.last_activity_at or i.created_at})
    for g in db.query(PersonaGeneration).filter_by(project_id=project_id).all():
        items.append({"type": "persona_generation", "id": g.id,
                      "title": f"Generated {g.created_count} persona(s)", "status": g.status,
                      "timestamp": g.created_at})
    items.sort(key=lambda x: (x["timestamp"] is not None, x["timestamp"]), reverse=True)
    return items[:limit]
