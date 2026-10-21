"""Interview sessions: persistence-first chat with a single synthetic persona."""
import json

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import config
from app.database.models import InterviewMessage, InterviewSession, Persona, Project, utcnow
from app.errors import BadRequest, Conflict
from app.schemas.interview import InterviewCreateIn
from app.services import ollama_service
from app.services.common import DISCLAIMER, persona_profile_text, project_context_text


def create_interview(db: Session, project: Project, body: InterviewCreateIn) -> InterviewSession:
    persona = db.get(Persona, body.persona_id)
    if not persona or persona.project_id != project.id:
        raise BadRequest("The selected persona does not belong to this project.")
    session = InterviewSession(project_id=project.id, persona_id=persona.id, title=body.title.strip(),
                               status="active", research_topic=body.research_topic,
                               research_objective=body.research_objective,
                               interview_guide=body.interview_guide, last_activity_at=utcnow())
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def message_count(db: Session, session_id: int) -> int:
    return db.query(func.count(InterviewMessage.id)).filter(InterviewMessage.session_id == session_id).scalar() or 0


def summary(db: Session, s: InterviewSession) -> dict:
    return {
        "id": s.id, "project_id": s.project_id, "persona_id": s.persona_id, "title": s.title,
        "status": s.status, "research_topic": s.research_topic, "research_objective": s.research_objective,
        "interview_guide": s.interview_guide, "created_at": s.created_at,
        "last_activity_at": s.last_activity_at or s.created_at, "completed_at": s.completed_at,
        "persona_name": s.persona.name if s.persona else None,
        "persona_occupation": s.persona.occupation if s.persona else None,
        "message_count": message_count(db, s.id),
    }


def detail(db: Session, s: InterviewSession) -> dict:
    d = summary(db, s)
    p = s.project
    d["persona"] = s.persona
    d["project"] = {"id": p.id, "name": p.name, "description": p.product_description,
                    "target_market": p.target_market, "research_objective": p.research_objective,
                    "category": p.category}
    d["messages"] = list(s.messages)
    d["disclaimer"] = DISCLAIMER
    return d


def _system_prompt(s: InterviewSession) -> str:
    text = (
        "You are role-playing a FICTIONAL, AI-generated research participant (a synthetic persona) being "
        "interviewed for product research. Reply in the first person as this persona, consistent with the "
        "profile and with everything you already said in this interview.\n"
        "Rules: do not claim to be a real person or a real customer; do not claim to have used the product "
        "unless the profile says so - talk about habits, expectations and needs; answer only what was asked; "
        "keep answers natural and brief (2-5 sentences); plain text only.\n\n"
        f"PERSONA PROFILE\n{persona_profile_text(s.persona)}\n\nCONTEXT\n{project_context_text(s.project)}")
    if s.research_topic:
        text += f"\nInterview topic: {s.research_topic}"
    if s.research_objective:
        text += f"\nInterview objective: {s.research_objective}"
    if s.interview_guide:
        text += f"\nInterviewer's guide (for context only): {s.interview_guide}"
    return text


def send_message(db: Session, session_id: int, text: str) -> tuple[InterviewMessage, InterviewMessage]:
    """Generate the reply FIRST, then store question + answer atomically (no orphaned questions)."""
    s = db.get(InterviewSession, session_id)
    if s.status != "active":
        raise Conflict("This interview has been completed and no longer accepts questions.")
    recent = (db.query(InterviewMessage).filter(InterviewMessage.session_id == s.id)
              .order_by(InterviewMessage.sequence_number.desc()).limit(config.INTERVIEW_CONTEXT_MESSAGES).all())
    history = [{"role": "assistant" if m.role == "persona" else "user", "content": m.message_text}
               for m in reversed(recent)]
    reply_text = ollama_service.generate_text(_system_prompt(s), text, history=history,
                                              temperature=0.5, max_tokens=350)
    try:
        last = db.query(func.coalesce(func.max(InterviewMessage.sequence_number), 0)).filter(
            InterviewMessage.session_id == s.id).scalar()
        q = InterviewMessage(session_id=s.id, role="researcher", message_text=text, sequence_number=last + 1)
        a = InterviewMessage(session_id=s.id, role="persona", message_text=reply_text, sequence_number=last + 2)
        db.add_all([q, a])
        s.last_activity_at = utcnow()
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("Another message was saved at the same time. Please send your question again.") from exc
    db.refresh(q)
    db.refresh(a)
    return q, a


def complete(db: Session, s: InterviewSession) -> InterviewSession:
    if s.status == "completed":
        return s
    if message_count(db, s.id) < 2:
        raise BadRequest("Ask at least one question and receive an answer before completing the interview.")
    s.status, s.completed_at, s.last_activity_at = "completed", utcnow(), utcnow()
    db.commit()
    db.refresh(s)
    return s


def summarize_with_ai(db: Session, s: InterviewSession) -> dict:
    if message_count(db, s.id) < 2:
        raise BadRequest("The interview has no transcript to summarise yet.")
    transcript = [{"role": m.role, "text": m.message_text[:600]} for m in s.messages]
    prompt = ("Summarise this SIMULATED interview with an AI-generated persona for a product researcher. "
              "Base the summary only on the transcript.\n"
              f"{json.dumps(transcript, ensure_ascii=False)}\n\n"
              'Return JSON: {"summary": "3-5 sentences", "needs": ["..."], "preferences": ["..."], '
              '"pain_points": ["..."], "recommendations": ["..."]}')
    data = ollama_service.generate_json(prompt, temperature=0.2, max_tokens=800)

    def lst(key):
        v = data.get(key) or []
        return [str(x).strip() for x in v if str(x).strip()][:6] if isinstance(v, list) else []
    return {"summary": str(data.get("summary") or "").strip(), "needs": lst("needs"),
            "preferences": lst("preferences"), "pain_points": lst("pain_points"),
            "recommendations": lst("recommendations")}
