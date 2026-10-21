from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import config
from app.schemas.persona import PersonaResponse


class InterviewCreateIn(BaseModel):
    persona_id: int
    title: str = Field(min_length=1, max_length=255)
    research_topic: str | None = Field(default=None, max_length=255)
    research_objective: str | None = Field(default=None, max_length=3000)
    interview_guide: str | None = Field(default=None, max_length=5000)

    @field_validator("title", mode="before")
    @classmethod
    def _t(cls, v):
        v = v.strip() if isinstance(v, str) else v
        if not v:
            raise ValueError("Interview title is required")
        return v


class InterviewCreate(InterviewCreateIn):
    """Legacy body for POST /interviews/ (project id in the body)."""
    project_id: int


class InterviewMessageCreate(BaseModel):
    message_text: str = Field(min_length=1)

    @field_validator("message_text", mode="before")
    @classmethod
    def _m(cls, v):
        v = v.strip() if isinstance(v, str) else v
        if not v:
            raise ValueError("Message cannot be empty")
        if len(v) > config.MAX_INTERVIEW_MESSAGE_CHARS:
            raise ValueError(f"Message is too long (max {config.MAX_INTERVIEW_MESSAGE_CHARS} characters)")
        return v


class InterviewMessageResponse(BaseModel):
    id: int
    session_id: int
    role: str
    message_text: str
    sequence_number: int | None = None
    created_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True)


class InterviewReplyResponse(BaseModel):
    session_id: int
    researcher_message: InterviewMessageResponse
    persona_reply: InterviewMessageResponse


class InterviewSessionResponse(BaseModel):
    id: int
    project_id: int
    persona_id: int
    title: str
    status: str
    research_topic: str | None = None
    research_objective: str | None = None
    interview_guide: str | None = None
    created_at: datetime | None = None
    last_activity_at: datetime | None = None
    completed_at: datetime | None = None
    persona_name: str | None = None
    persona_occupation: str | None = None
    message_count: int = 0


class InterviewDetailOut(InterviewSessionResponse):
    persona: PersonaResponse
    project: dict
    messages: list[InterviewMessageResponse]
    disclaimer: str = ("AI-generated synthetic research. The persona's answers are simulated and are "
                       "not genuine customer feedback.")
