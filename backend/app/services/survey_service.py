"""Survey creation, idempotent AI processing and result assembly."""
import json
import logging
import re

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import config
from app.database.models import (
    Persona, Project, SurveyExperiment, SurveyParticipant, SurveyQuestion, SurveyResponse, utcnow,
)
from app.errors import AppError, BadGateway, BadRequest, Conflict, ServiceUnavailable
from app.schemas.survey import QuestionIn, SurveyCreateIn, SurveyUpdate
from app.services import ollama_service
from app.services.common import DISCLAIMER, is_stale, persona_profile_text, project_context_text

logger = logging.getLogger("synuser.surveys")


# ----------------------------------------------------------------- create / update
def _validated_personas(db: Session, project_id: int, persona_ids: list[int]) -> list[Persona]:
    personas = db.query(Persona).filter(Persona.id.in_(persona_ids)).all()
    found = {p.id for p in personas}
    missing = [i for i in persona_ids if i not in found]
    if missing:
        raise BadRequest(f"Persona(s) not found: {missing}")
    foreign = [p.id for p in personas if p.project_id != project_id]
    if foreign:
        raise BadRequest(f"Persona(s) {foreign} do not belong to this project")
    order = {pid: n for n, pid in enumerate(persona_ids)}
    return sorted(personas, key=lambda p: order[p.id])


def _apply_questions(db: Session, survey: SurveyExperiment, questions: list[QuestionIn]) -> None:
    existing = {q.id: q for q in survey.questions}
    keep = set()
    for position, qi in enumerate(questions, start=1):
        opts = json.dumps(qi.options) if qi.options else None
        q = existing.get(qi.id) if qi.id else None
        if q:
            if q.question_text != qi.question_text or q.question_type != qi.question_type:
                q.responses.clear()     # answers belong to the old wording; they are regenerated on retry
            q.question_text, q.question_type, q.question_order, q.options = \
                qi.question_text, qi.question_type, position, opts
            keep.add(q.id)
        else:
            survey.questions.append(SurveyQuestion(
                question_text=qi.question_text, question_type=qi.question_type,
                question_order=position, options=opts))
    for qid, q in existing.items():
        if qid not in keep:
            survey.questions.remove(q)


def create_survey(db: Session, project: Project, body: SurveyCreateIn) -> SurveyExperiment:
    personas = _validated_personas(db, project.id, body.persona_ids)
    survey = SurveyExperiment(project_id=project.id, title=body.title, description=body.description,
                              research_objective=body.research_objective,
                              research_topic=body.research_topic, status="draft")
    db.add(survey)
    _apply_questions(db, survey, body.questions)
    for p in personas:
        survey.participants.append(SurveyParticipant(persona_id=p.id))
    db.commit()
    db.refresh(survey)
    return survey


def update_survey(db: Session, survey: SurveyExperiment, body: SurveyUpdate) -> SurveyExperiment:
    if survey.status == "processing" and not is_stale(survey.processing_started_at, config.STALE_PROCESSING_MINUTES):
        raise Conflict("This survey is being processed; wait for it to finish before editing.")
    data = body.model_dump(exclude_unset=True)
    for f in ("title", "description", "research_objective", "research_topic"):
        if f in data and data[f] is not None:
            setattr(survey, f, data[f])
    changed = False
    if body.questions is not None:
        _apply_questions(db, survey, body.questions)
        changed = True
    if body.persona_ids is not None:
        personas = _validated_personas(db, survey.project_id, body.persona_ids)
        wanted = {p.id for p in personas}
        for part in list(survey.participants):
            if part.persona_id not in wanted:
                db.query(SurveyResponse).filter(
                    SurveyResponse.persona_id == part.persona_id,
                    SurveyResponse.question_id.in_([q.id for q in survey.questions])
                ).delete(synchronize_session=False)
                survey.participants.remove(part)
        have = {part.persona_id for part in survey.participants}
        for p in personas:
            if p.id not in have:
                survey.participants.append(SurveyParticipant(persona_id=p.id))
        changed = True
    if changed:
        db.flush()
        db.refresh(survey)
        done = _response_count(db, survey)
        expected = len(survey.questions) * len(survey.participants)
        survey.status = "draft" if done == 0 else ("completed" if done >= expected else "partial")
        survey.completed_at = survey.completed_at if survey.status == "completed" else None
        if survey.status == "completed" and survey.completed_at is None:
            survey.completed_at = utcnow()
    db.commit()
    db.refresh(survey)
    return survey


# ----------------------------------------------------------------- counts / summaries
def _response_count(db: Session, survey: SurveyExperiment) -> int:
    return (db.query(func.count(SurveyResponse.id))
            .join(SurveyQuestion, SurveyQuestion.id == SurveyResponse.question_id)
            .join(SurveyParticipant, (SurveyParticipant.persona_id == SurveyResponse.persona_id)
                  & (SurveyParticipant.survey_id == SurveyQuestion.survey_id))
            .filter(SurveyQuestion.survey_id == survey.id).scalar() or 0)


def summarize(db: Session, survey: SurveyExperiment) -> dict:
    q = db.query(func.count(SurveyQuestion.id)).filter(SurveyQuestion.survey_id == survey.id).scalar() or 0
    p = db.query(func.count(SurveyParticipant.id)).filter(SurveyParticipant.survey_id == survey.id).scalar() or 0
    return {
        "id": survey.id, "project_id": survey.project_id, "title": survey.title,
        "description": survey.description, "research_objective": survey.research_objective,
        "research_topic": survey.research_topic, "status": survey.status or "draft",
        "created_at": survey.created_at, "completed_at": survey.completed_at,
        "question_count": q, "persona_count": p, "response_count": _response_count(db, survey),
        "expected_responses": q * p,
    }


def detail(db: Session, survey: SurveyExperiment) -> dict:
    d = summarize(db, survey)
    d["questions"] = list(survey.questions)
    d["participants"] = [{"id": x.persona.id, "name": x.persona.name, "occupation": x.persona.occupation}
                         for x in survey.participants]
    return d


# ----------------------------------------------------------------- results
def build_results(db: Session, survey: SurveyExperiment, errors: dict | None = None) -> dict:
    errors = errors or {}
    participants = [x.persona for x in survey.participants]
    pmap = {p.id: p for p in participants}
    questions = list(survey.questions)
    rows = (db.query(SurveyResponse).filter(SurveyResponse.question_id.in_([q.id for q in questions]))
            .order_by(SurveyResponse.id).all()) if questions else []
    by_q: dict[int, dict[int, SurveyResponse]] = {}
    for r in rows:
        if r.persona_id in pmap:
            by_q.setdefault(r.question_id, {})[r.persona_id] = r
    results, failed, total = [], [], 0
    processing = survey.status == "processing"
    for q in questions:
        answers = []
        for p in participants:                       # stable order = order personas were selected
            r = by_q.get(q.id, {}).get(p.id)
            if r:
                answers.append({"response_id": r.id, "persona_id": p.id, "persona_name": p.name,
                                "persona_occupation": p.occupation, "answer": r.response_text,
                                "created_at": r.created_at})
            elif not processing and survey.status in ("partial", "failed", "completed"):
                failed.append({"question_id": q.id, "question_text": q.question_text,
                               "persona_id": p.id, "persona_name": p.name,
                               "error": errors.get((q.id, p.id))})
        total += len(answers)
        results.append({"question_id": q.id, "question_text": q.question_text, "question": q.question_text,
                        "question_type": q.question_type, "position": q.question_order,
                        "answer_count": len(answers), "answers": answers})
    project = survey.project
    return {
        "survey_id": survey.id, "survey_title": survey.title, "status": survey.status or "draft",
        "project": {"id": project.id, "name": project.name, "description": project.product_description,
                    "target_market": project.target_market, "research_objective": project.research_objective,
                    "category": project.category},
        "research_objective": survey.research_objective, "research_topic": survey.research_topic,
        "created_at": survey.created_at, "completed_at": survey.completed_at,
        "total_questions": len(questions), "total_personas": len(participants),
        "total_responses": total, "expected_responses": len(questions) * len(participants),
        "last_error": survey.last_error,
        "personas": [{"id": p.id, "name": p.name, "age": p.age, "occupation": p.occupation,
                      "location": p.location, "goals": p.goals, "pain_points": p.pain_points,
                      "preferences": p.preferences} for p in participants],
        "failed_items": failed, "results": results, "disclaimer": DISCLAIMER,
    }


# ----------------------------------------------------------------- AI processing
def _build_answer_prompt(project: Project, survey: SurveyExperiment, persona: Persona,
                         question: SurveyQuestion, previous: list[tuple[str, str]]) -> tuple[str, str]:
    system = (
        "You are role-playing a FICTIONAL, AI-generated research participant (a synthetic persona) in a "
        "simulated product-research survey. Answer in the first person, consistent with the profile below.\n"
        "Rules: do not claim to be a real person; do not claim to have actually used the product unless the "
        "profile says so (speak about expectations, habits and needs instead); stay on the question; "
        "be concrete and concise (2-4 sentences); output only the answer text.\n\n"
        f"PARTICIPANT PROFILE\n{persona_profile_text(persona)}\n\nCONTEXT\n{project_context_text(project)}")
    if survey.research_topic:
        system += f"\nResearch topic: {survey.research_topic}"
    if survey.research_objective:
        system += f"\nSurvey objective: {survey.research_objective}"
    prompt = ""
    if previous:
        prompt += "Your earlier answers in this survey (stay consistent with them):\n" + "\n".join(
            f"- Q: {q}\n  A: {a[:300]}" for q, a in previous[-3:]) + "\n\n"
    prompt += f"Question: {question.question_text}\n"
    opts = json.loads(question.options) if question.options else None
    if question.question_type == "single_choice":
        prompt += f"Choose exactly ONE of: {', '.join(opts)}. Start with the chosen option, then one sentence of reasoning.\n"
    elif question.question_type == "multiple_choice":
        prompt += f"Choose one or more of: {', '.join(opts)}. List your choices first, then one sentence of reasoning.\n"
    elif question.question_type == "rating":
        prompt += "Give a rating as an integer from 1 (lowest) to 5 (highest) first, then one sentence of reasoning.\n"
    return system, prompt


def _clean_answer(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^(answer|response)\s*:\s*", "", text, flags=re.IGNORECASE)
    if len(text) > 1 and text[0] == text[-1] and text[0] in "\"'“”":
        text = text[1:-1].strip()
    return text


def process_survey(db: Session, survey_id: int) -> tuple[dict, dict]:
    """Generate every missing (question, persona) answer. Idempotent: existing answers are kept,
    so retrying only fills the gaps. Each answer is committed immediately (partial progress survives)."""
    survey = db.get(SurveyExperiment, survey_id)
    if survey.status == "processing" and not is_stale(survey.processing_started_at, config.STALE_PROCESSING_MINUTES):
        raise Conflict("This survey is already being processed.")
    questions = list(survey.questions)
    participants = [x.persona for x in survey.participants]
    if not questions:
        raise BadRequest("The survey has no questions.")
    if not participants:
        raise BadRequest("The survey has no selected personas.")
    ollama_service.ensure_ready()

    survey.status, survey.processing_started_at, survey.last_error = "processing", utcnow(), None
    db.commit()

    project = survey.project
    errors: dict[tuple[int, int], str] = {}
    consecutive_ai_down = 0
    skipped = created = 0
    try:
        for persona in participants:
            earlier: list[tuple[str, str]] = []
            have = {r.question_id: r.response_text for r in
                    db.query(SurveyResponse).filter(SurveyResponse.persona_id == persona.id,
                                                    SurveyResponse.question_id.in_([q.id for q in questions]))}
            for q in questions:
                if q.id in have:
                    skipped += 1
                    earlier.append((q.question_text, have[q.id]))
                    continue
                if consecutive_ai_down >= 2:
                    errors[(q.id, persona.id)] = "Skipped: local AI service stopped responding."
                    continue
                try:
                    system, prompt = _build_answer_prompt(project, survey, persona, q, earlier)
                    answer = _clean_answer(ollama_service.generate_text(system, prompt, temperature=0.6, max_tokens=350))
                    if not answer:
                        raise BadGateway("The model returned an empty answer.")
                    db.add(SurveyResponse(question_id=q.id, persona_id=persona.id, response_text=answer))
                    db.commit()
                    created += 1
                    consecutive_ai_down = 0
                    earlier.append((q.question_text, answer))
                except IntegrityError:
                    db.rollback()               # another request stored it first; keep that one
                    skipped += 1
                except ServiceUnavailable as exc:
                    db.rollback()
                    consecutive_ai_down += 1
                    errors[(q.id, persona.id)] = exc.detail
                except AppError as exc:
                    db.rollback()
                    errors[(q.id, persona.id)] = exc.detail
                except Exception:
                    db.rollback()
                    logger.exception("Unexpected survey answer failure")
                    errors[(q.id, persona.id)] = "Unexpected error while generating this response."
    finally:
        db.rollback()
        survey = db.get(SurveyExperiment, survey_id)
        total = len(questions) * len(participants)
        done = _response_count(db, survey)
        survey.status = "completed" if done >= total else ("partial" if done else "failed")
        survey.completed_at = utcnow() if survey.status == "completed" else None
        survey.last_error = next(iter(errors.values()), None)
        db.commit()
    db.refresh(survey)
    return build_results(db, survey, errors), {"created": created, "skipped_existing": skipped, "failed": len(errors)}


def summarize_with_ai(db: Session, survey: SurveyExperiment) -> dict:
    results = build_results(db, survey)
    if not results["total_responses"]:
        raise BadRequest("Process the survey before requesting a summary.")
    qa = [{"question": r["question_text"],
           "answers": [{"persona": a["persona_name"], "answer": a["answer"][:400]} for a in r["answers"]]}
          for r in results["results"]]
    prompt = ("Summarise these SIMULATED survey answers for a product researcher. They are AI-generated, "
              "not real customers. Base your summary only on the answers.\n"
              f"{json.dumps(qa, ensure_ascii=False)}\n\n"
              'Return JSON: {"summary": "3-5 sentences", "themes": ["short theme", "..."]}')
    data = ollama_service.generate_json(prompt, temperature=0.2, max_tokens=700)
    summary = str(data.get("summary") or "").strip()
    themes = data.get("themes") or []
    themes = [str(t).strip() for t in themes if str(t).strip()] if isinstance(themes, list) else []
    if not summary:
        raise BadGateway("The model returned no summary.")
    return {"survey_id": survey.id, "summary": summary, "themes": themes[:8]}
