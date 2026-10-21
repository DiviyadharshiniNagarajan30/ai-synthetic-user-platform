from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app import config

QUESTION_TYPES = {"open_ended", "single_choice", "multiple_choice", "rating"}


class QuestionIn(BaseModel):
    id: int | None = None
    question_text: str = Field(min_length=1, max_length=1000)
    question_type: str = "open_ended"
    question_order: int = Field(default=1, ge=1)
    options: list[str] | None = None

    @field_validator("question_text", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _check(self):
        if not self.question_text:
            raise ValueError("Question text cannot be blank")
        if self.question_type not in QUESTION_TYPES:
            raise ValueError(f"question_type must be one of {sorted(QUESTION_TYPES)}")
        if self.question_type in ("single_choice", "multiple_choice"):
            opts = [o.strip() for o in (self.options or []) if o and o.strip()]
            if len(opts) < 2:
                raise ValueError("Choice questions need at least two options")
            self.options = opts
        else:
            self.options = None
        return self


# Legacy create body (POST /surveys/)
class SurveyCreate(BaseModel):
    project_id: int
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=3000)


QuestionCreate = QuestionIn  # legacy name


class SurveyCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    research_objective: str | None = Field(default=None, max_length=3000)
    research_topic: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=3000)
    questions: list[QuestionIn] = Field(min_length=1)
    persona_ids: list[int] = Field(min_length=1)

    @field_validator("title", mode="before")
    @classmethod
    def _t(cls, v):
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _check(self):
        if not self.title:
            raise ValueError("Survey title is required")
        if len(self.questions) > config.MAX_SURVEY_QUESTIONS:
            raise ValueError(f"At most {config.MAX_SURVEY_QUESTIONS} questions per survey")
        if len(set(self.persona_ids)) > config.MAX_SURVEY_PERSONAS:
            raise ValueError(f"At most {config.MAX_SURVEY_PERSONAS} personas per survey")
        self.persona_ids = list(dict.fromkeys(self.persona_ids))
        return self


class SurveyUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    research_objective: str | None = Field(default=None, max_length=3000)
    research_topic: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=3000)
    questions: list[QuestionIn] | None = Field(default=None, min_length=1)
    persona_ids: list[int] | None = Field(default=None, min_length=1)


class QuestionOut(BaseModel):
    id: int
    survey_id: int
    question_text: str
    question_type: str
    question_order: int
    options: list[str] | None = None
    model_config = ConfigDict(from_attributes=True)

    @field_validator("options", mode="before")
    @classmethod
    def _parse(cls, v):
        import json
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except ValueError:
                return None
        return v


QuestionResponse = QuestionOut  # legacy name


class PersonaBrief(BaseModel):
    id: int
    name: str
    occupation: str | None = None


class SurveySummaryOut(BaseModel):
    id: int
    project_id: int
    title: str
    description: str | None = None
    research_objective: str | None = None
    research_topic: str | None = None
    status: str
    created_at: datetime | None = None
    completed_at: datetime | None = None
    question_count: int
    persona_count: int
    response_count: int
    expected_responses: int


class SurveyDetailOut(SurveySummaryOut):
    questions: list[QuestionOut]
    participants: list[PersonaBrief]


class SurveyResponse(BaseModel):
    """Legacy summary returned by POST /surveys/."""
    id: int
    project_id: int
    title: str
    description: str | None = None
    model_config = ConfigDict(from_attributes=True)


class AnswerOut(BaseModel):
    response_id: int
    persona_id: int
    persona_name: str
    persona_occupation: str | None = None
    answer: str
    created_at: datetime | None = None


class QuestionResultOut(BaseModel):
    question_id: int
    question_text: str
    question: str                       # legacy alias of question_text
    question_type: str
    position: int
    answer_count: int
    answers: list[AnswerOut]


class FailedItemOut(BaseModel):
    question_id: int
    question_text: str
    persona_id: int
    persona_name: str
    error: str | None = None


class PersonaProfileOut(BaseModel):
    id: int
    name: str
    age: int | None = None
    occupation: str | None = None
    location: str | None = None
    goals: str | None = None
    pain_points: str | None = None
    preferences: str | None = None


class SurveyResultsOut(BaseModel):
    survey_id: int
    survey_title: str
    status: str
    project: dict
    research_objective: str | None = None
    research_topic: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None
    total_questions: int
    total_personas: int
    total_responses: int
    expected_responses: int
    last_error: str | None = None
    personas: list[PersonaProfileOut]
    failed_items: list[FailedItemOut]
    results: list[QuestionResultOut]
    disclaimer: str = ("AI-generated synthetic research. Responses are simulated by a language model "
                       "and are not genuine customer feedback or statistically representative data.")


class InsightOut(BaseModel):
    survey_id: int
    summary: str
    themes: list[str]
    disclaimer: str = "AI-generated interpretation of synthetic responses."


# --- legacy insight schema retained for the original /insights route -------------------
class PersonaInterest(BaseModel):
    persona_id: int
    persona_name: str
    would_use_product: bool
    reason: str


class InsightResponse(BaseModel):
    survey_id: int
    total_answers_analyzed: int
    common_themes: list[str]
    sentiment_summary: dict[str, int]
    agreement_patterns: list[str]
    persona_interests: list[PersonaInterest]
    overall_summary: str
