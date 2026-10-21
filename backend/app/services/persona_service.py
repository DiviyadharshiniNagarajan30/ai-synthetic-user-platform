"""Persona generation, validation and persistence."""
import difflib
import json
import logging
import random
import re

from sqlalchemy.orm import Session

from app import config
from app.database.models import BehaviorProfile, Persona, PersonaGeneration, Project
from app.errors import AppError, BadGateway, ServiceUnavailable
from app.schemas.persona import PersonaGenerateRequest
from app.services import ollama_service

logger = logging.getLogger("synuser.personas")

DEFAULT_OCCUPATIONS = [
    "College student", "Software developer", "Teacher", "Healthcare professional",
    "Business owner", "Manager", "Accountant", "Freelancer", "Homemaker", "Retired individual",
]
SCORE_FIELDS = ["expense_tracking", "saving_habit", "shopping_frequency",
                "impulse_buying", "budget_awareness", "technology_usage"]
TEXT_FIELDS = ["personality", "goals", "preferences", "pain_points", "research_interests"]
INCOME_CURRENCY = "INR"


def _as_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        value = "; ".join(str(v).strip() for v in value if str(v).strip())
    elif isinstance(value, dict):
        value = "; ".join(f"{k}: {v}" for k, v in value.items())
    value = str(value).strip()
    return value or None


def _as_number(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"\d[\d,]*\.?\d*", str(value))
    return float(match.group(0).replace(",", "")) if match else None


def validate_persona_data(raw: dict, *, target_age: int | None, age_range: tuple[int | None, int | None],
                          want_scores: bool, assigned_occupation: str | None) -> dict:
    """Coerce + validate model output. Raises ValueError with a readable reason."""
    name = _as_text(raw.get("name"))
    if not name or len(name) > 100:
        raise ValueError("missing or invalid name")
    data = {"name": name}
    data["age"] = None
    age = _as_number(raw.get("age"))
    lo, hi = age_range
    if age is not None and 10 <= age <= 100 and (lo is None or age >= lo) and (hi is None or age <= hi):
        data["age"] = int(age)
    elif target_age:
        data["age"] = target_age          # model ignored the constraint; keep the requested age
    occupation = assigned_occupation or _as_text(raw.get("occupation"))
    data["occupation"] = occupation[:100] if occupation else None
    income = _as_number(raw.get("income"))
    data["income"] = round(income, 2) if income is not None and 0 <= income < 1e9 else None
    for f in ("location", "experience_level"):
        t = _as_text(raw.get(f))
        data[f] = t[:150] if t else None
    for f in TEXT_FIELDS:
        t = _as_text(raw.get(f))
        data[f] = t[:3000] if t else None
    missing = [f for f in ("personality", "goals", "pain_points") if not data[f]]
    if missing:
        raise ValueError("missing fields: " + ", ".join(missing))
    scores = None
    if want_scores:
        src = raw.get("behavior_scores")
        if isinstance(src, dict):
            scores = {}
            for f in SCORE_FIELDS:
                n = _as_number(src.get(f))
                if n is None:
                    scores = None
                    break
                scores[f] = max(1, min(5, int(round(n))))
    data["_scores"] = scores
    return data


def _is_duplicate(data: dict, existing: list[dict]) -> bool:
    for e in existing:
        if e["name"].strip().lower() == data["name"].strip().lower():
            return True
        a = f"{data.get('goals','')} {data.get('pain_points','')}".lower()
        b = f"{e.get('goals') or ''} {e.get('pain_points') or ''}".lower()
        if a and b and difflib.SequenceMatcher(None, a, b).ratio() > 0.88:
            return True
    return False


def build_prompt(project: Project, req: PersonaGenerateRequest, *, occupation: str | None,
                 target_age: int | None, avoid_names: list[str], index: int, total: int,
                 duplicate_hint: bool) -> str:
    lines = [
        "Create ONE fictional synthetic user persona for product research. It is a simulation, not a real person.",
        f"Project: {project.name}",
        f"Product / research context: {req.product_context or project.product_description or 'n/a'}",
        f"Research objective: {project.research_objective or 'n/a'}",
        f"Research topic: {req.research_topic or 'general'}",
        f"Target audience: {project.target_market or 'n/a'}",
        f"This is persona {index} of {total}; make it clearly different from the others.",
        "",
        "Constraints for this persona:",
    ]
    lines.append(f"- Occupation: {occupation}" if occupation else
                 "- Occupation: choose one that fits the research context (or none if irrelevant)")
    if target_age:
        lines.append(f"- Age: {target_age}")
    if req.include_income:
        band = ""
        if req.income_min is not None or req.income_max is not None:
            band = f" between {req.income_min or 0:g} and {req.income_max if req.income_max is not None else 'any'}"
        lines.append(f"- Monthly income in {INCOME_CURRENCY} as a plain number{band} (use null if irrelevant)")
    else:
        lines.append("- Income: null (not relevant)")
    for label, val in (("Location/region", req.location), ("Experience level", req.experience_level),
                       ("Personality traits", req.personality), ("Goals", req.goals),
                       ("Preferences", req.preferences), ("Pain points", req.pain_points)):
        if val:
            lines.append(f"- {label}: {val}")
    if req.custom_instructions:
        lines.append(f"- Extra instructions: {req.custom_instructions}")
    if avoid_names:
        lines.append(f"- Do NOT reuse these names: {', '.join(avoid_names[-15:])}")
    if duplicate_hint:
        lines.append("- Your previous attempt was too similar to an existing persona. Use a very different name, "
                     "background and concerns.")
    schema = {"name": "fictional full name", "age": 30, "occupation": "string or null", "income": 40000,
              "location": "city, region", "experience_level": "e.g. beginner/intermediate/expert",
              "personality": "1-2 sentences", "goals": "1-2 sentences", "preferences": "1-2 sentences",
              "pain_points": "1-2 sentences", "research_interests": "1 sentence"}
    if req.include_behavior_scores:
        schema["behavior_scores"] = {f: 3 for f in SCORE_FIELDS}
        lines.append("- behavior_scores: integers 1-5 for every key")
    lines += ["", "Return ONLY a JSON object with exactly these keys:", json.dumps(schema, indent=1),
              "Keep every text value short and non-empty."]
    return "\n".join(lines)


def generate_personas(db: Session, project: Project, req: PersonaGenerateRequest) -> tuple[PersonaGeneration, list[str]]:
    ollama_service.ensure_ready()      # fail fast, before creating any record

    criteria = req.model_dump()
    generation = PersonaGeneration(project_id=project.id, criteria=json.dumps(criteria),
                                   requested_count=req.count, created_count=0, status="running",
                                   model_name=config.OLLAMA_MODEL)
    db.add(generation)
    db.commit()
    db.refresh(generation)

    pool = list(req.occupations)
    if req.custom_occupation and req.custom_occupation.strip():
        pool.append(req.custom_occupation.strip()[:100])
    pool = list(dict.fromkeys(pool))
    rng = random.Random()

    existing = [{"name": p.name, "goals": p.goals, "pain_points": p.pain_points}
                for p in db.query(Persona).filter(Persona.project_id == project.id).all()]
    errors: list[str] = []
    created = 0
    abort: AppError | None = None

    for i in range(1, req.count + 1):
        occupation = pool[(i - 1) % len(pool)] if pool else None
        lo, hi = req.age_min, req.age_max
        target_age = rng.randint(lo or 18, hi or max(lo or 18, 70)) if (lo or hi) else None
        saved = False
        duplicate_hint = False
        reason = "unknown error"
        for _attempt in range(2):
            prompt = build_prompt(project, req, occupation=occupation, target_age=target_age,
                                  avoid_names=[e["name"] for e in existing], index=i, total=req.count,
                                  duplicate_hint=duplicate_hint)
            try:
                raw = ollama_service.generate_json(prompt, temperature=0.8, max_tokens=700)
                data = validate_persona_data(raw, target_age=target_age, age_range=(lo, hi),
                                             want_scores=req.include_behavior_scores,
                                             assigned_occupation=occupation)
            except ServiceUnavailable as exc:
                abort, reason = exc, exc.detail
                break
            except (BadGateway, ValueError) as exc:
                reason = getattr(exc, "detail", None) or str(exc)
                continue
            if _is_duplicate(data, existing):
                reason, duplicate_hint = "duplicate or near-identical persona", True
                continue
            scores = data.pop("_scores")
            try:
                persona = Persona(project_id=project.id, generation_id=generation.id, **data)
                db.add(persona)
                db.flush()
                if scores:
                    db.add(BehaviorProfile(persona_id=persona.id, **scores))
                db.commit()
            except Exception:
                db.rollback()
                reason = "could not save persona"
                logger.exception("Persona save failed")
                continue
            existing.append({"name": data["name"], "goals": data["goals"], "pain_points": data["pain_points"]})
            created += 1
            saved = True
            break
        if not saved:
            errors.append(f"Persona {i}: {reason}")
        if abort:
            break

    generation.created_count = created
    generation.status = "completed" if created == req.count else ("partial" if created else "failed")
    generation.error_message = "\n".join(errors) if errors else None
    db.commit()
    db.refresh(generation)
    if created == 0:
        raise (abort or BadGateway("No personas could be generated: " + "; ".join(errors[:3])))
    return generation, errors
