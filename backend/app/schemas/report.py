
from pydantic import BaseModel


class ResearchReportResponse(BaseModel):
    project_id: int
    project_name: str
    product_description: str | None = None
    target_market: str | None = None
    research_objective: str | None = None

    total_personas: int
    total_surveys: int
    total_survey_responses: int
    total_interview_sessions: int
    total_interview_messages: int

    survey_findings: list[str]
    common_themes: list[str]
    sentiment_summary: dict[str, int]
    persona_interests: list[dict]
    interview_findings: list[str]
    recommendations: list[str]
    conclusion: str
