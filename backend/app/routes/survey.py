import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import (
    Persona, SurveyExperiment, SurveyParticipant, SurveyQuestion, SurveyResponse as SurveyResponseModel,
)
from app.errors import BadRequest, Conflict
from app.schemas.survey import (
    InsightOut, InsightResponse, QuestionIn, QuestionOut, SurveyCreate, SurveyCreateIn,
    SurveyDetailOut, SurveyResponse, SurveyResultsOut, SurveySummaryOut, SurveyUpdate,
)
from app.services import ollama_service, survey_service
from app.services.common import get_project_or_404, get_survey_or_404

router = APIRouter(tags=["Survey Mode"])


@router.post("/projects/{project_id}/surveys", response_model=SurveyDetailOut, status_code=201)
def create_survey(project_id: int, body: SurveyCreateIn, db: Session = Depends(get_db)):
    project = get_project_or_404(db, project_id)
    survey = survey_service.create_survey(db, project, body)
    return survey_service.detail(db, survey)


@router.get("/projects/{project_id}/surveys")
def list_surveys(project_id: int, q: str | None = None, status: str | None = None,
                 date_from: str | None = None, date_to: str | None = None,
                 limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                 db: Session = Depends(get_db)):
    get_project_or_404(db, project_id)
    query = db.query(SurveyExperiment).filter_by(project_id=project_id)
    if q:
        query = query.filter(SurveyExperiment.title.like(f"%{q.strip()}%"))
    if status:
        query = query.filter(SurveyExperiment.status == status)
    if date_from:
        query = query.filter(SurveyExperiment.created_at >= date_from)
    if date_to:
        query = query.filter(SurveyExperiment.created_at < f"{date_to} 23:59:59.999999")
    total = query.count()
    rows = query.order_by(SurveyExperiment.id.desc()).offset(offset).limit(limit).all()
    return {"items": [SurveySummaryOut(**survey_service.summarize(db, s)) for s in rows],
            "total": total, "limit": limit, "offset": offset}


@router.get("/surveys/{survey_id}", response_model=SurveyDetailOut)
def get_survey(survey_id: int, db: Session = Depends(get_db)):
    return survey_service.detail(db, get_survey_or_404(db, survey_id))


@router.patch("/surveys/{survey_id}", response_model=SurveyDetailOut)
def update_survey(survey_id: int, body: SurveyUpdate, db: Session = Depends(get_db)):
    survey = survey_service.update_survey(db, get_survey_or_404(db, survey_id), body)
    return survey_service.detail(db, survey)


@router.delete("/surveys/{survey_id}")
def delete_survey(survey_id: int, db: Session = Depends(get_db)):
    survey = get_survey_or_404(db, survey_id)
    if survey.status == "processing" and not survey_service.is_stale(
            survey.processing_started_at, survey_service.config.STALE_PROCESSING_MINUTES):
        raise Conflict("This survey is being processed and cannot be deleted right now.")
    db.delete(survey)
    db.commit()
    return {"deleted": True, "survey_id": survey_id}


@router.post("/surveys/{survey_id}/process", response_model=dict)
def process_survey(survey_id: int, db: Session = Depends(get_db)):
    """Generates all missing answers (idempotent - safe to call again to retry failures)."""
    get_survey_or_404(db, survey_id)
    results, stats = survey_service.process_survey(db, survey_id)
    return {"results": SurveyResultsOut(**results).model_dump(mode="json"), "processing": stats}


@router.get("/surveys/{survey_id}/results", response_model=SurveyResultsOut)
def survey_results(survey_id: int, db: Session = Depends(get_db)):
    return survey_service.build_results(db, get_survey_or_404(db, survey_id))


@router.post("/surveys/{survey_id}/summary", response_model=InsightOut)
def survey_summary(survey_id: int, db: Session = Depends(get_db)):
    return survey_service.summarize_with_ai(db, get_survey_or_404(db, survey_id))


# ------------------------------------------------------------------ legacy routes (kept)
@router.post("/surveys/", response_model=SurveyResponse, status_code=201, tags=["Legacy"])
def create_survey_legacy(body: SurveyCreate, db: Session = Depends(get_db)):
    get_project_or_404(db, body.project_id)
    survey = SurveyExperiment(project_id=body.project_id, title=body.title.strip(),
                              description=body.description, status="draft")
    db.add(survey)
    db.commit()
    db.refresh(survey)
    return survey


@router.get("/surveys/", response_model=list[SurveyResponse], tags=["Legacy"])
def list_surveys_legacy(db: Session = Depends(get_db)):
    return db.query(SurveyExperiment).order_by(SurveyExperiment.id).all()


@router.post("/surveys/{survey_id}/questions", response_model=QuestionOut, status_code=201, tags=["Legacy"])
def add_question(survey_id: int, body: QuestionIn, db: Session = Depends(get_db)):
    survey = get_survey_or_404(db, survey_id)
    nxt = (db.query(func.coalesce(func.max(SurveyQuestion.question_order), 0))
           .filter_by(survey_id=survey_id).scalar() or 0) + 1
    q = SurveyQuestion(survey_id=survey_id, question_text=body.question_text,
                       question_type=body.question_type, question_order=nxt,
                       options=json.dumps(body.options) if body.options else None)
    db.add(q)
    db.commit()
    db.refresh(q)
    return q


@router.get("/surveys/{survey_id}/questions", response_model=list[QuestionOut], tags=["Legacy"])
def get_questions(survey_id: int, db: Session = Depends(get_db)):
    return get_survey_or_404(db, survey_id).questions


@router.post("/surveys/{survey_id}/generate-responses", tags=["Legacy"])
def generate_responses_legacy(survey_id: int, db: Session = Depends(get_db)):
    """Original name. If the survey has no explicit participants, every persona of the project joins."""
    survey = get_survey_or_404(db, survey_id)
    if not survey.participants:
        for p in db.query(Persona).filter_by(project_id=survey.project_id).all():
            survey.participants.append(SurveyParticipant(persona_id=p.id))
        db.commit()
        if not survey.participants:
            raise BadRequest("Generate at least one persona for this project")
    results, stats = survey_service.process_survey(db, survey_id)
    return {"survey_id": survey_id, "message": "AI survey responses generated",
            "total_personas": results["total_personas"], "total_questions": results["total_questions"],
            "total_responses": results["total_responses"], **stats}


@router.get("/surveys/{survey_id}/insights", response_model=InsightResponse, tags=["Legacy"])
def survey_insights_legacy(survey_id: int, db: Session = Depends(get_db)):
    survey = get_survey_or_404(db, survey_id)
    results = survey_service.build_results(db, survey)
    answers = [{"response_id": a["response_id"], "persona_id": a["persona_id"], "persona_name": a["persona_name"],
                "question": r["question_text"], "answer": a["answer"]}
               for r in results["results"] for a in r["answers"]]
    if not answers:
        raise BadRequest("Generate survey responses before extracting insights")
    prompt = (
        "You are an AI product research analyst. Analyse these SYNTHETIC (AI-generated) survey answers; "
        "they are not real customer evidence.\n" + json.dumps(answers, ensure_ascii=False) +
        '\nReturn ONLY JSON: {"common_themes": [str], "agreement_patterns": [str], "persona_interests": '
        '[{"persona_id": int, "persona_name": str, "would_use_product": bool, "reason": str}], '
        '"sentiments": [{"response_id": int, "sentiment": "positive|neutral|negative"}], "overall_summary": str}. '
        "One sentiment per response_id; base conclusions only on the answers.")
    data = ollama_service.generate_json(prompt, temperature=0.1, max_tokens=1500)
    counts = {"positive": 0, "neutral": 0, "negative": 0}
    valid = {a["response_id"] for a in answers}
    seen = set()
    for item in data.get("sentiments", []):
        rid, s = item.get("response_id"), str(item.get("sentiment", "")).lower().strip()
        if rid in valid and rid not in seen and s in counts:
            counts[s] += 1
            seen.add(rid)
    return {"survey_id": survey_id, "total_answers_analyzed": len(answers),
            "common_themes": data.get("common_themes", []), "sentiment_summary": counts,
            "agreement_patterns": data.get("agreement_patterns", []),
            "persona_interests": data.get("persona_interests", []),
            "overall_summary": data.get("overall_summary", "")}
