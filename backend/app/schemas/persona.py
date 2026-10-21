import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app import config


class PersonaFields(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    age: int | None = Field(default=None, ge=1, le=120)
    occupation: str | None = Field(default=None, max_length=100)
    income: float | None = Field(default=None, ge=0, le=9_999_999_999)
    location: str | None = Field(default=None, max_length=150)
    experience_level: str | None = Field(default=None, max_length=150)
    personality: str | None = Field(default=None, max_length=3000)
    goals: str | None = Field(default=None, max_length=3000)
    preferences: str | None = Field(default=None, max_length=3000)
    pain_points: str | None = Field(default=None, max_length=3000)
    research_interests: str | None = Field(default=None, max_length=3000)

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, v):
        v = (v or "").strip() if isinstance(v, str) else v
        if not v:
            raise ValueError("Persona name is required")
        return v


class PersonaIn(PersonaFields):
    """Manual persona creation inside a project (POST /projects/{id}/personas)."""


class PersonaCreate(PersonaFields):
    """Legacy body for POST /personas/ (project id in the body)."""
    project_id: int


class PersonaUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    age: int | None = Field(default=None, ge=1, le=120)
    occupation: str | None = Field(default=None, max_length=100)
    income: float | None = Field(default=None, ge=0, le=9_999_999_999)
    location: str | None = Field(default=None, max_length=150)
    experience_level: str | None = Field(default=None, max_length=150)
    personality: str | None = Field(default=None, max_length=3000)
    goals: str | None = Field(default=None, max_length=3000)
    preferences: str | None = Field(default=None, max_length=3000)
    pain_points: str | None = Field(default=None, max_length=3000)
    research_interests: str | None = Field(default=None, max_length=3000)


class BehaviorOut(BaseModel):
    expense_tracking: int | None = None
    saving_habit: int | None = None
    shopping_frequency: int | None = None
    impulse_buying: int | None = None
    budget_awareness: int | None = None
    technology_usage: int | None = None
    model_config = ConfigDict(from_attributes=True)


class PersonaResponse(PersonaFields):
    id: int
    project_id: int
    generation_id: int | None = None
    additional_profile_data: dict | None = None
    behavior: BehaviorOut | None = None
    created_at: datetime | None = None
    is_synthetic: bool = True      # always true: every persona here is AI-generated/simulated
    model_config = ConfigDict(from_attributes=True)

    @field_validator("additional_profile_data", mode="before")
    @classmethod
    def _parse_json(cls, v):
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except ValueError:
                return None
        return v if isinstance(v, dict) else None


class PersonaGenerateRequest(BaseModel):
    count: int = Field(default=3, ge=1)
    research_topic: str | None = Field(default=None, max_length=255)
    product_context: str | None = Field(default=None, max_length=3000)
    occupations: list[str] = Field(default_factory=list, max_length=20)
    custom_occupation: str | None = Field(default=None, max_length=150)
    age_min: int | None = Field(default=None, ge=10, le=100)
    age_max: int | None = Field(default=None, ge=10, le=100)
    income_min: float | None = Field(default=None, ge=0)
    income_max: float | None = Field(default=None, ge=0)
    include_income: bool = True
    experience_level: str | None = Field(default=None, max_length=150)
    location: str | None = Field(default=None, max_length=150)
    personality: str | None = Field(default=None, max_length=500)
    goals: str | None = Field(default=None, max_length=500)
    preferences: str | None = Field(default=None, max_length=500)
    pain_points: str | None = Field(default=None, max_length=500)
    custom_instructions: str | None = Field(default=None, max_length=1500)
    include_behavior_scores: bool = False

    @model_validator(mode="after")
    def _check(self):
        if self.count > config.MAX_PERSONAS_PER_REQUEST:
            raise ValueError(f"At most {config.MAX_PERSONAS_PER_REQUEST} personas can be generated per request")
        if self.age_min and self.age_max and self.age_min > self.age_max:
            raise ValueError("Minimum age cannot exceed maximum age")
        if self.income_min is not None and self.income_max is not None and self.income_min > self.income_max:
            raise ValueError("Minimum income cannot exceed maximum income")
        self.occupations = [o.strip()[:100] for o in self.occupations if o and o.strip()]
        return self


class PersonaGenerationOut(BaseModel):
    id: int
    project_id: int
    criteria: dict | None = None
    requested_count: int
    created_count: int
    status: str
    error_message: str | None = None
    model_name: str | None = None
    created_at: datetime | None = None
    personas: list[PersonaResponse] = []
    model_config = ConfigDict(from_attributes=True)

    @field_validator("criteria", mode="before")
    @classmethod
    def _parse(cls, v):
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except ValueError:
                return None
        return v if isinstance(v, dict) else None


class PersonaGenerateResult(BaseModel):
    generation: PersonaGenerationOut
    errors: list[str] = []
