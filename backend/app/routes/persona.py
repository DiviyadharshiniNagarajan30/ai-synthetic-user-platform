from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database.models import (
    BehaviorProfile, Persona, PersonaGeneration, SurveyResponse, InterviewSession,
)
from app.database.connection import get_db
from app.errors import Conflict
from app.schemas.persona import (
    PersonaCreate, PersonaGenerateRequest, PersonaGenerateResult, PersonaGenerationOut,
    PersonaIn, PersonaResponse, PersonaUpdate,
)
from app.services import persona_service
from app.services.common import get_persona_or_404, get_project_or_404

router = APIRouter(tags=["Personas"])


def _list_query(db, project_id, q, occupation, generation_id, age_min, age_max):
    query = db.query(Persona).filter(Persona.project_id == project_id)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(Persona.name.like(like), Persona.occupation.like(like),
                                 Persona.goals.like(like), Persona.pain_points.like(like),
                                 Persona.location.like(like)))
    if occupation:
        query = query.filter(Persona.occupation == occupation)
    if generation_id:
        query = query.filter(Persona.generation_id == generation_id)
    if age_min is not None:
        query = query.filter(Persona.age >= age_min)
    if age_max is not None:
        query = query.filter(Persona.age <= age_max)
    return query


@router.get("/projects/{project_id}/personas")
def list_project_personas(project_id: int, q: str | None = None, occupation: str | None = None,
                          generation_id: int | None = None, age_min: int | None = None,
                          age_max: int | None = None, limit: int = Query(100, ge=1, le=500),
                          offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    get_project_or_404(db, project_id)
    query = _list_query(db, project_id, q, occupation, generation_id, age_min, age_max)
    total = query.count()
    items = query.order_by(Persona.id.desc()).offset(offset).limit(limit).all()
    occupations = [o for (o,) in db.query(Persona.occupation).filter(
        Persona.project_id == project_id, Persona.occupation.isnot(None)).distinct().order_by(Persona.occupation)]
    return {"items": [PersonaResponse.model_validate(p) for p in items], "total": total,
            "limit": limit, "offset": offset, "occupations": occupations}


@router.post("/projects/{project_id}/personas", response_model=PersonaResponse, status_code=201)
def create_project_persona(project_id: int, body: PersonaIn, db: Session = Depends(get_db)):
    get_project_or_404(db, project_id)
    persona = Persona(project_id=project_id, **body.model_dump())
    db.add(persona)
    db.commit()
    db.refresh(persona)
    return persona


@router.post("/projects/{project_id}/personas/generate", response_model=PersonaGenerateResult, status_code=201)
def generate_project_personas(project_id: int, body: PersonaGenerateRequest, db: Session = Depends(get_db)):
    project = get_project_or_404(db, project_id)
    generation, errors = persona_service.generate_personas(db, project, body)
    return {"generation": generation, "errors": errors}


@router.get("/projects/{project_id}/persona-generations")
def list_generations(project_id: int, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                     status: str | None = None, date_from: str | None = None, date_to: str | None = None,
                     db: Session = Depends(get_db)):
    get_project_or_404(db, project_id)
    query = db.query(PersonaGeneration).filter_by(project_id=project_id)
    if status:
        query = query.filter(PersonaGeneration.status == status)
    if date_from:
        query = query.filter(PersonaGeneration.created_at >= date_from)
    if date_to:
        query = query.filter(PersonaGeneration.created_at < f"{date_to} 23:59:59.999999")
    total = query.count()
    items = query.order_by(PersonaGeneration.id.desc()).offset(offset).limit(limit).all()
    return {"items": [PersonaGenerationOut.model_validate(g) for g in items], "total": total,
            "limit": limit, "offset": offset}


@router.get("/persona-generations/{generation_id}", response_model=PersonaGenerationOut)
def get_generation(generation_id: int, db: Session = Depends(get_db)):
    from app.errors import NotFound
    generation = db.get(PersonaGeneration, generation_id)
    if not generation:
        raise NotFound("Persona generation not found")
    return generation


# ---------------------------------------------------------------- single persona routes
@router.get("/personas/{persona_id}", response_model=PersonaResponse)
def get_persona(persona_id: int, db: Session = Depends(get_db)):
    return get_persona_or_404(db, persona_id)


@router.patch("/personas/{persona_id}", response_model=PersonaResponse)
def update_persona(persona_id: int, body: PersonaUpdate, db: Session = Depends(get_db)):
    persona = get_persona_or_404(db, persona_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        if key == "name" and not value:
            continue
        setattr(persona, key, value)
    db.commit()
    db.refresh(persona)
    return persona


@router.delete("/personas/{persona_id}")
def delete_persona(persona_id: int, force: bool = Query(False), db: Session = Depends(get_db)):
    persona = get_persona_or_404(db, persona_id)
    answers = db.query(func.count(SurveyResponse.id)).filter_by(persona_id=persona_id).scalar()
    interviews = db.query(func.count(InterviewSession.id)).filter_by(persona_id=persona_id).scalar()
    if (answers or interviews) and not force:
        raise Conflict(
            f"This persona has {answers} saved survey response(s) and {interviews} interview(s). "
            "Deleting the persona permanently removes them. Confirm to delete everything.",
            code="persona_in_use", extra={"survey_responses": answers, "interviews": interviews})
    db.delete(persona)
    db.commit()
    return {"deleted": True, "persona_id": persona_id}


# ---------------------------------------------------------------- legacy routes (kept)
@router.post("/personas/", response_model=PersonaResponse, status_code=201, tags=["Legacy"])
def create_persona_legacy(body: PersonaCreate, db: Session = Depends(get_db)):
    get_project_or_404(db, body.project_id)
    persona = Persona(**body.model_dump())
    db.add(persona)
    db.commit()
    db.refresh(persona)
    return persona


@router.get("/personas/", response_model=list[PersonaResponse], tags=["Legacy"])
def list_personas_legacy(db: Session = Depends(get_db)):
    return db.query(Persona).order_by(Persona.id).all()


@router.post("/personas/generate/{project_id}", tags=["Legacy"])
def generate_one_persona_legacy(project_id: int, db: Session = Depends(get_db)):
    """Original endpoint: generates ONE persona (+ finance behaviour scores)."""
    project = get_project_or_404(db, project_id)
    generation, _ = persona_service.generate_personas(
        db, project, PersonaGenerateRequest(count=1, include_behavior_scores=True))
    persona = db.query(Persona).filter_by(generation_id=generation.id).first()
    return {"message": "AI persona generated and saved successfully",
            "persona": PersonaResponse.model_validate(persona),
            "behavior": PersonaResponse.model_validate(persona).behavior}
