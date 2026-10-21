from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import InterviewMessage, InterviewSession
from app.schemas.interview import (
    InterviewCreate, InterviewCreateIn, InterviewDetailOut, InterviewMessageCreate,
    InterviewMessageResponse, InterviewReplyResponse, InterviewSessionResponse,
)
from app.services import interview_service
from app.services.common import get_interview_or_404, get_project_or_404

router = APIRouter(tags=["Interview Mode"])


@router.post("/projects/{project_id}/interviews", response_model=InterviewDetailOut, status_code=201)
def create_interview(project_id: int, body: InterviewCreateIn, db: Session = Depends(get_db)):
    project = get_project_or_404(db, project_id)
    session = interview_service.create_interview(db, project, body)
    return interview_service.detail(db, session)


@router.get("/projects/{project_id}/interviews")
def list_interviews(project_id: int, q: str | None = None, status: str | None = None,
                    date_from: str | None = None, date_to: str | None = None,
                    limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                    db: Session = Depends(get_db)):
    get_project_or_404(db, project_id)
    query = db.query(InterviewSession).filter_by(project_id=project_id)
    if q:
        query = query.filter(InterviewSession.title.like(f"%{q.strip()}%"))
    if status:
        query = query.filter(InterviewSession.status == status)
    if date_from:
        query = query.filter(InterviewSession.created_at >= date_from)
    if date_to:
        query = query.filter(InterviewSession.created_at < f"{date_to} 23:59:59.999999")
    total = query.count()
    rows = query.order_by(InterviewSession.id.desc()).offset(offset).limit(limit).all()
    return {"items": [InterviewSessionResponse(**interview_service.summary(db, s)) for s in rows],
            "total": total, "limit": limit, "offset": offset}


@router.get("/interviews/{interview_id}", response_model=InterviewDetailOut)
def get_interview(interview_id: int, db: Session = Depends(get_db)):
    return interview_service.detail(db, get_interview_or_404(db, interview_id))


@router.post("/interviews/{interview_id}/messages", response_model=InterviewReplyResponse)
def send_message(interview_id: int, body: InterviewMessageCreate, db: Session = Depends(get_db)):
    get_interview_or_404(db, interview_id)
    q, a = interview_service.send_message(db, interview_id, body.message_text)
    return {"session_id": interview_id, "researcher_message": q, "persona_reply": a}


@router.get("/interviews/{interview_id}/messages", response_model=list[InterviewMessageResponse])
def list_messages(interview_id: int, db: Session = Depends(get_db)):
    return get_interview_or_404(db, interview_id).messages


@router.post("/interviews/{interview_id}/complete", response_model=InterviewSessionResponse)
def complete_interview(interview_id: int, db: Session = Depends(get_db)):
    s = interview_service.complete(db, get_interview_or_404(db, interview_id))
    return interview_service.summary(db, s)


@router.post("/interviews/{interview_id}/summary")
def summarize_interview(interview_id: int, db: Session = Depends(get_db)):
    """AI-generated interpretation of the saved transcript (labelled as such by the UI and PDF)."""
    data = interview_service.summarize_with_ai(db, get_interview_or_404(db, interview_id))
    return {**data, "disclaimer": "AI-generated interpretation of a simulated interview."}


@router.delete("/interviews/{interview_id}")
def delete_interview(interview_id: int, db: Session = Depends(get_db)):
    s = get_interview_or_404(db, interview_id)
    db.delete(s)
    db.commit()
    return {"deleted": True, "interview_id": interview_id}


@router.post("/interviews/", response_model=InterviewSessionResponse, status_code=201, tags=["Legacy"])
def create_interview_legacy(body: InterviewCreate, db: Session = Depends(get_db)):
    project = get_project_or_404(db, body.project_id)
    s = interview_service.create_interview(db, project, InterviewCreateIn(**body.model_dump(exclude={"project_id"})))
    return interview_service.summary(db, s)
