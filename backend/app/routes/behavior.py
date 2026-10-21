from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import BehaviorProfile, Persona
from app.schemas.behavior import BehaviorCreate, BehaviorResponse

router = APIRouter(
    prefix="/behaviors",
    tags=["Behavior Profiles"]
)


@router.post("/", response_model=BehaviorResponse)
def create_behavior(
    behavior: BehaviorCreate,
    db: Session = Depends(get_db)
):

    persona = db.query(Persona).filter(
        Persona.id == behavior.persona_id
    ).first()

    if not persona:
        raise HTTPException(
            status_code=404,
            detail="Persona not found"
        )

    existing = db.query(BehaviorProfile).filter(
        BehaviorProfile.persona_id == behavior.persona_id
    ).first()

    if existing:
        raise HTTPException(
            status_code=400,
            detail="Behavior profile already exists"
        )

    new_behavior = BehaviorProfile(
        **behavior.model_dump()
    )

    db.add(new_behavior)
    db.commit()
    db.refresh(new_behavior)

    return new_behavior


@router.get("/{persona_id}", response_model=BehaviorResponse)
def get_behavior(
    persona_id: int,
    db: Session = Depends(get_db)
):

    behavior = db.query(BehaviorProfile).filter(
        BehaviorProfile.persona_id == persona_id
    ).first()

    if not behavior:
        raise HTTPException(
            status_code=404,
            detail="Behavior profile not found"
        )

    return behavior