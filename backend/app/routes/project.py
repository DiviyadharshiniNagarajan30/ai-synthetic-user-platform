from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import (
    InterviewSession, Persona, Project, Report, SurveyExperiment, utcnow,
)
from app.errors import Conflict
from app.schemas.project import ProjectCreate, ProjectResponse, ProjectUpdate
from app.services import stats_service
from app.services.common import get_project_or_404

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.post("/", response_model=ProjectResponse, status_code=201)
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    project = Project(**body.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/", response_model=list[ProjectResponse])
def list_projects(db: Session = Depends(get_db)):
    return db.query(Project).order_by(Project.id.desc()).all()


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: int, db: Session = Depends(get_db)):
    return get_project_or_404(db, project_id)


@router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(project_id: int, body: ProjectUpdate, db: Session = Depends(get_db)):
    project = get_project_or_404(db, project_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        if key == "name" and not value:
            continue
        setattr(project, key, value)
    project.updated_at = utcnow()
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}")
def delete_project(project_id: int, force: bool = Query(False, description="Also delete all research records"),
                   db: Session = Depends(get_db)):
    project = get_project_or_404(db, project_id)
    counts = {
        "personas": db.query(func.count(Persona.id)).filter_by(project_id=project_id).scalar(),
        "surveys": db.query(func.count(SurveyExperiment.id)).filter_by(project_id=project_id).scalar(),
        "interviews": db.query(func.count(InterviewSession.id)).filter_by(project_id=project_id).scalar(),
    }
    if any(counts.values()) and not force:
        raise Conflict(
            "This project contains research records (" + ", ".join(f"{v} {k}" for k, v in counts.items() if v) +
            "). Deleting it permanently removes all of them. Confirm to delete everything.",
            code="project_not_empty", extra={"counts": counts})
    db.delete(project)
    db.commit()
    return {"deleted": True, "project_id": project_id, "removed": counts}


@router.get("/{project_id}/statistics")
def project_statistics(project_id: int, db: Session = Depends(get_db)):
    get_project_or_404(db, project_id)
    return stats_service.statistics(db, project_id)


@router.get("/{project_id}/activity")
def project_activity(project_id: int, limit: int = Query(15, ge=1, le=100), db: Session = Depends(get_db)):
    get_project_or_404(db, project_id)
    return {"items": stats_service.activity(db, project_id, limit)}


@router.get("/{project_id}/reports")
def project_reports(project_id: int, db: Session = Depends(get_db)):
    get_project_or_404(db, project_id)
    rows = db.query(Report).filter_by(project_id=project_id).order_by(Report.id.desc()).limit(100).all()
    return {"items": [{"id": r.id, "report_type": r.report_type, "survey_id": r.survey_id,
                       "interview_id": r.interview_id, "filename": r.filename,
                       "generated_at": r.generated_at} for r in rows]}
