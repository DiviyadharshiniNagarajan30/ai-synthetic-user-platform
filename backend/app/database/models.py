"""SQLAlchemy models.

Existing table and column names from the original project are preserved
(projects, personas, behavior_profiles, survey_experiments, survey_questions,
survey_responses, interview_sessions, interview_messages). New columns are nullable or
have defaults so `database/migrate.py` can add them to an existing database without
touching existing rows. New tables: persona_generations, survey_participants, reports.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    DECIMAL, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database.connection import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC, MySQL friendly


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    product_description = Column(Text)          # shown as "Description" in the UI
    target_market = Column(Text)                # shown as "Target audience"
    research_objective = Column(Text)
    category = Column(String(100))
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    personas = relationship("Persona", back_populates="project", cascade="all, delete-orphan")
    generations = relationship("PersonaGeneration", back_populates="project", cascade="all, delete-orphan")
    surveys = relationship("SurveyExperiment", back_populates="project", cascade="all, delete-orphan")
    interviews = relationship("InterviewSession", back_populates="project", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="project", cascade="all, delete-orphan")


class PersonaGeneration(Base):
    """One persona-generation run (history entry)."""
    __tablename__ = "persona_generations"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    criteria = Column(Text)                     # JSON of the form values used
    requested_count = Column(Integer, nullable=False, default=0)
    created_count = Column(Integer, nullable=False, default=0)
    status = Column(String(30), nullable=False, default="completed")   # completed|partial|failed
    error_message = Column(Text)
    model_name = Column(String(100))
    created_at = Column(DateTime, default=utcnow)

    project = relationship("Project", back_populates="generations")
    personas = relationship("Persona", back_populates="generation")


class Persona(Base):
    __tablename__ = "personas"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    generation_id = Column(Integer, ForeignKey("persona_generations.id", ondelete="SET NULL"), index=True)

    name = Column(String(100), nullable=False)
    age = Column(Integer)
    occupation = Column(String(100))
    income = Column(DECIMAL(12, 2))
    location = Column(String(150))
    experience_level = Column(String(150))
    personality = Column(Text)
    goals = Column(Text)
    preferences = Column(Text)
    pain_points = Column(Text)
    research_interests = Column(Text)
    additional_profile_data = Column(Text)      # JSON string
    created_at = Column(DateTime, default=utcnow)

    project = relationship("Project", back_populates="personas")
    generation = relationship("PersonaGeneration", back_populates="personas")
    behavior = relationship("BehaviorProfile", back_populates="persona", uselist=False,
                            cascade="all, delete-orphan")
    participations = relationship("SurveyParticipant", back_populates="persona", cascade="all, delete-orphan")
    responses = relationship("SurveyResponse", back_populates="persona", cascade="all, delete-orphan")
    interviews = relationship("InterviewSession", back_populates="persona", cascade="all, delete-orphan")


class BehaviorProfile(Base):
    __tablename__ = "behavior_profiles"

    id = Column(Integer, primary_key=True, index=True)
    persona_id = Column(Integer, ForeignKey("personas.id"), nullable=False, unique=True)

    expense_tracking = Column(Integer)
    saving_habit = Column(Integer)
    shopping_frequency = Column(Integer)
    impulse_buying = Column(Integer)
    budget_awareness = Column(Integer)
    technology_usage = Column(Integer)

    persona = relationship("Persona", back_populates="behavior")


class SurveyExperiment(Base):
    __tablename__ = "survey_experiments"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    research_objective = Column(Text)
    research_topic = Column(String(255))
    status = Column(String(30), default="draft")  # draft|processing|completed|partial|failed
    created_at = Column(DateTime, default=utcnow)
    processing_started_at = Column(DateTime)
    completed_at = Column(DateTime)
    last_error = Column(Text)

    project = relationship("Project", back_populates="surveys")
    questions = relationship("SurveyQuestion", back_populates="survey", cascade="all, delete-orphan",
                             order_by="SurveyQuestion.question_order")
    participants = relationship("SurveyParticipant", back_populates="survey", cascade="all, delete-orphan")


class SurveyQuestion(Base):
    __tablename__ = "survey_questions"

    id = Column(Integer, primary_key=True, index=True)
    survey_id = Column(Integer, ForeignKey("survey_experiments.id"), nullable=False, index=True)
    question_text = Column(Text, nullable=False)
    question_type = Column(String(50), nullable=False, default="open_ended")
    question_order = Column(Integer, nullable=False, default=1)
    options = Column(Text)                      # JSON list for choice questions

    survey = relationship("SurveyExperiment", back_populates="questions")
    responses = relationship("SurveyResponse", back_populates="question", cascade="all, delete-orphan")


class SurveyParticipant(Base):
    __tablename__ = "survey_participants"
    __table_args__ = (UniqueConstraint("survey_id", "persona_id", name="uq_participant_survey_persona"),)

    id = Column(Integer, primary_key=True, index=True)
    survey_id = Column(Integer, ForeignKey("survey_experiments.id", ondelete="CASCADE"), nullable=False, index=True)
    persona_id = Column(Integer, ForeignKey("personas.id", ondelete="CASCADE"), nullable=False, index=True)

    survey = relationship("SurveyExperiment", back_populates="participants")
    persona = relationship("Persona", back_populates="participations")


class SurveyResponse(Base):
    __tablename__ = "survey_responses"
    __table_args__ = (UniqueConstraint("question_id", "persona_id", name="uq_response_question_persona"),)

    id = Column(Integer, primary_key=True, index=True)
    question_id = Column(Integer, ForeignKey("survey_questions.id"), nullable=False, index=True)
    persona_id = Column(Integer, ForeignKey("personas.id"), nullable=False, index=True)
    response_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)

    question = relationship("SurveyQuestion", back_populates="responses")
    persona = relationship("Persona", back_populates="responses")


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    persona_id = Column(Integer, ForeignKey("personas.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False, default="active")   # active|completed
    research_topic = Column(String(255))
    research_objective = Column(Text)
    interview_guide = Column(Text)
    created_at = Column(DateTime, default=utcnow)
    last_activity_at = Column(DateTime, default=utcnow)
    completed_at = Column(DateTime)

    project = relationship("Project", back_populates="interviews")
    persona = relationship("Persona", back_populates="interviews")
    messages = relationship("InterviewMessage", back_populates="session", cascade="all, delete-orphan",
                            order_by="InterviewMessage.sequence_number")


class InterviewMessage(Base):
    __tablename__ = "interview_messages"
    __table_args__ = (UniqueConstraint("session_id", "sequence_number", name="uq_message_session_sequence"),)

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("interview_sessions.id"), nullable=False, index=True)
    role = Column(String(20), nullable=False)        # researcher | persona
    message_text = Column(Text, nullable=False)
    sequence_number = Column(Integer)
    created_at = Column(DateTime, default=utcnow)

    session = relationship("InterviewSession", back_populates="messages")


class Report(Base):
    """Metadata for generated PDF reports (the PDF itself is rendered on demand)."""
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    report_type = Column(String(30), nullable=False)   # survey | interview
    survey_id = Column(Integer, ForeignKey("survey_experiments.id", ondelete="SET NULL"))
    interview_id = Column(Integer, ForeignKey("interview_sessions.id", ondelete="SET NULL"))
    filename = Column(String(255), nullable=False)
    generated_at = Column(DateTime, default=utcnow)

    project = relationship("Project", back_populates="reports")


Index("ix_reports_type", Report.report_type)
