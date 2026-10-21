import httpx
import pytest
from pypdf import PdfReader
from io import BytesIO

from app.services import ollama_service
from app.tests.conftest import make_persona


def pdf_text(content: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(BytesIO(content)).pages)


# ---------------------------------------------------------------- health / projects
def test_health_endpoints(client):
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["database"] is True
    assert client.get("/health/database").json()["connected"] is True
    assert client.get("/health/ollama").json()["reachable"] is True


def test_project_crud_and_validation(client):
    assert client.post("/projects/", json={"name": "   "}).status_code == 422
    assert client.post("/projects/", json={}).status_code == 422
    p = client.post("/projects/", json={"name": " Alpha ", "category": "Fintech"}).json()
    assert p["name"] == "Alpha" and p["created_at"]
    assert client.get(f"/projects/{p['id']}").json()["category"] == "Fintech"
    upd = client.patch(f"/projects/{p['id']}", json={"product_description": "Desc"}).json()
    assert upd["product_description"] == "Desc" and upd["name"] == "Alpha"
    assert [x["id"] for x in client.get("/projects/").json()] == [p["id"]]
    assert client.get("/projects/9999").status_code == 404
    assert client.delete(f"/projects/{p['id']}").status_code == 200
    assert client.get(f"/projects/{p['id']}").status_code == 404


def test_project_delete_requires_force_when_it_has_research(client, project, personas):
    r = client.delete(f"/projects/{project['id']}")
    assert r.status_code == 409 and r.json()["counts"]["personas"] == 3
    assert client.get(f"/projects/{project['id']}").status_code == 200   # still there
    assert client.delete(f"/projects/{project['id']}?force=true").status_code == 200
    assert client.get(f"/projects/{project['id']}/personas").status_code == 404


# ---------------------------------------------------------------- personas
def test_persona_create_get_update_filter_delete(client, project, personas):
    pid = project["id"]
    listing = client.get(f"/projects/{pid}/personas").json()
    assert listing["total"] == 3 and set(listing["occupations"]) == {"Software Engineer", "College Student", "Business Owner"}
    assert listing["items"][0]["is_synthetic"] is True
    assert client.get(f"/projects/{pid}/personas?q=priya").json()["total"] == 1
    assert client.get(f"/projects/{pid}/personas?occupation=Business Owner").json()["total"] == 1
    one = personas[0]
    assert client.get(f"/personas/{one['id']}").json()["name"] == "Arun Kumar"
    assert client.patch(f"/personas/{one['id']}", json={"age": 41}).json()["age"] == 41
    assert client.post(f"/projects/{pid}/personas", json={"age": 3}).status_code == 422
    assert client.get("/personas/12345").status_code == 404
    assert client.delete(f"/personas/{one['id']}").status_code == 200


def test_persona_generation_saves_history_and_diverse_occupations(client, project, ai):
    pid = project["id"]
    r = client.post(f"/projects/{pid}/personas/generate", json={
        "count": 3, "occupations": ["Teacher", "Accountant"], "custom_occupation": "Farmer",
        "age_min": 25, "age_max": 60, "include_behavior_scores": True})
    assert r.status_code == 201, r.text
    gen = r.json()["generation"]
    assert gen["status"] == "completed" and gen["created_count"] == 3
    assert [p["occupation"] for p in gen["personas"]] == ["Teacher", "Accountant", "Farmer"]
    assert all(25 <= p["age"] <= 60 for p in gen["personas"])
    assert gen["personas"][0]["behavior"]["saving_habit"] == 3
    assert gen["personas"][0]["preferences"] == "simple UI; alerts"          # list coerced to text
    hist = client.get(f"/projects/{pid}/persona-generations").json()
    assert hist["total"] == 1 and hist["items"][0]["criteria"]["custom_occupation"] == "Farmer"
    assert client.get(f"/persona-generations/{gen['id']}").json()["created_count"] == 3
    assert client.get(f"/projects/{pid}/personas?generation_id={gen['id']}").json()["total"] == 3


def test_persona_generation_limits_and_validation(client, project):
    pid = project["id"]
    assert client.post(f"/projects/{pid}/personas/generate", json={"count": 500}).status_code == 422
    assert client.post(f"/projects/{pid}/personas/generate", json={"count": 0}).status_code == 422
    assert client.post(f"/projects/{pid}/personas/generate", json={"count": 2, "age_min": 50, "age_max": 20}).status_code == 422
    assert client.post("/projects/999/personas/generate", json={"count": 1}).status_code == 404


def test_persona_generation_handles_bad_json_then_recovers(client, project, ai):
    ai.persona_overrides = ["{not json", '{"name": "Only Name"}']     # attempt 1 invalid JSON x2 -> then good
    r = client.post(f"/projects/{project['id']}/personas/generate", json={"count": 1})
    assert r.status_code == 201
    assert r.json()["generation"]["created_count"] == 1 and r.json()["errors"] == []


def test_persona_generation_all_invalid_creates_no_personas(client, project, ai):
    ai.persona_overrides = ["{bad"] * 8
    r = client.post(f"/projects/{project['id']}/personas/generate", json={"count": 1})
    assert r.status_code == 502
    assert client.get(f"/projects/{project['id']}/personas").json()["total"] == 0
    hist = client.get(f"/projects/{project['id']}/persona-generations").json()["items"]
    assert hist[0]["status"] == "failed" and hist[0]["created_count"] == 0


def test_persona_generation_rejects_duplicates(client, project, ai):
    same = ('{"name":"Same Person","age":30,"personality":"p","goals":"identical goals text here",'
            '"pain_points":"identical pain text here"}')
    ai.persona_overrides = [same, same, same, same]
    r = client.post(f"/projects/{project['id']}/personas/generate", json={"count": 2})
    assert r.status_code == 201
    g = r.json()["generation"]
    assert g["status"] == "partial" and g["created_count"] == 1 and "duplicate" in r.json()["errors"][0]


def test_persona_generation_ollama_down_creates_nothing(client, project, monkeypatch):
    monkeypatch.setattr(ollama_service, "status", lambda: {"reachable": False, "model_installed": False})
    r = client.post(f"/projects/{project['id']}/personas/generate", json={"count": 1})
    assert r.status_code == 503 and "local AI service is unavailable" in r.json()["detail"]
    assert client.get(f"/projects/{project['id']}/persona-generations").json()["total"] == 0


def test_model_missing_message(client, project, monkeypatch):
    monkeypatch.setattr(ollama_service, "status", lambda: {"reachable": True, "model_installed": False})
    r = client.post(f"/projects/{project['id']}/personas/generate", json={"count": 1})
    assert r.status_code == 503 and "ollama pull" in r.json()["detail"]


# ---------------------------------------------------------------- surveys
SURVEY = {"title": "Expense survey", "research_objective": "Find pains", "research_topic": "Budgeting",
          "questions": [{"question_text": "What is your biggest challenge in managing monthly expenses?"},
                        {"question_text": "Which feature would help you the most?"}]}


def create_survey(client, project, personas, **over):
    body = {**SURVEY, "persona_ids": [p["id"] for p in personas], **over}
    r = client.post(f"/projects/{project['id']}/surveys", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_survey_create_stores_questions_and_participants(client, project, personas):
    s = create_survey(client, project, personas)
    assert s["status"] == "draft" and s["question_count"] == 2 and s["persona_count"] == 3
    assert [q["question_order"] for q in s["questions"]] == [1, 2]
    assert [x["name"] for x in s["participants"]] == ["Arun Kumar", "Priya", "Meena"]
    assert client.get(f"/surveys/{s['id']}").json()["questions"][0]["question_text"].startswith("What is")


def test_survey_validation(client, project, personas):
    pid = project["id"]
    ids = [p["id"] for p in personas]
    assert client.post(f"/projects/{pid}/surveys", json={**SURVEY, "persona_ids": []}).status_code == 422
    assert client.post(f"/projects/{pid}/surveys", json={"title": "x", "questions": [], "persona_ids": ids}).status_code == 422
    assert client.post(f"/projects/{pid}/surveys", json={**SURVEY, "persona_ids": ids, "title": " "}).status_code == 422
    bad_choice = {**SURVEY, "persona_ids": ids, "questions": [{"question_text": "Pick", "question_type": "single_choice"}]}
    assert client.post(f"/projects/{pid}/surveys", json=bad_choice).status_code == 422
    assert client.post(f"/projects/{pid}/surveys", json={**SURVEY, "persona_ids": [99999]}).status_code == 400
    assert client.post("/projects/999/surveys", json={**SURVEY, "persona_ids": ids}).status_code == 404


def test_survey_rejects_persona_from_another_project(client, project, personas):
    other = client.post("/projects/", json={"name": "Other"}).json()
    foreign = make_persona(client, other["id"], "Foreign", "Doctor")
    r = client.post(f"/projects/{project['id']}/surveys",
                    json={**SURVEY, "persona_ids": [personas[0]["id"], foreign["id"]]})
    assert r.status_code == 400 and "do not belong" in r.json()["detail"]


def test_survey_processing_saves_all_responses_and_results_shape(client, project, personas):
    s = create_survey(client, project, personas)
    r = client.post(f"/surveys/{s['id']}/process")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["processing"]["created"] == 6 and body["processing"]["failed"] == 0
    res = client.get(f"/surveys/{s['id']}/results").json()          # re-read from DB, not the process reply
    assert res["status"] == "completed" and res["total_responses"] == 6 and res["expected_responses"] == 6
    q1 = res["results"][0]
    assert q1["question_text"] == q1["question"] and q1["answer_count"] == 3
    assert [(a["persona_name"], a["persona_occupation"]) for a in q1["answers"]] == [
        ("Arun Kumar", "Software Engineer"), ("Priya", "College Student"), ("Meena", "Business Owner")]
    assert all(a["answer"] for a in q1["answers"]) and res["failed_items"] == []
    assert "synthetic" in res["disclaimer"].lower()


def test_survey_processing_is_idempotent(client, project, personas, ai):
    s = create_survey(client, project, personas)
    client.post(f"/surveys/{s['id']}/process")
    calls_before = len(ai.calls)
    again = client.post(f"/surveys/{s['id']}/process").json()
    assert again["processing"]["created"] == 0 and again["processing"]["skipped_existing"] == 6
    assert len(ai.calls) == calls_before                              # no new model calls
    assert client.get(f"/surveys/{s['id']}/results").json()["total_responses"] == 6


def test_survey_partial_failure_is_kept_reported_and_retryable(client, project, personas, ai):
    s = create_survey(client, project, personas)
    ai.fail_text_when = "Which feature"
    r = client.post(f"/surveys/{s['id']}/process").json()
    assert r["processing"]["created"] == 3 and r["processing"]["failed"] == 3
    res = client.get(f"/surveys/{s['id']}/results").json()
    assert res["status"] == "partial" and res["total_responses"] == 3
    assert len(res["failed_items"]) == 3 and res["failed_items"][0]["question_text"].startswith("Which feature")
    assert res["last_error"]
    ai.fail_text_when = None                                           # retry only fills the gaps
    r2 = client.post(f"/surveys/{s['id']}/process").json()
    assert r2["processing"]["created"] == 3 and r2["processing"]["skipped_existing"] == 3
    assert client.get(f"/surveys/{s['id']}/results").json()["status"] == "completed"


def test_survey_processing_ollama_unavailable(client, project, personas, monkeypatch):
    s = create_survey(client, project, personas)
    monkeypatch.setattr(ollama_service, "status", lambda: {"reachable": False, "model_installed": False})
    r = client.post(f"/surveys/{s['id']}/process")
    assert r.status_code == 503
    assert client.get(f"/surveys/{s['id']}").json()["status"] == "draft"     # not stuck in 'processing'


def test_survey_ai_dies_midway_preserves_saved_answers(client, project, personas, ai):
    s = create_survey(client, project, personas)
    real = ai.__call__
    state = {"n": 0}

    def flaky(messages, **kw):
        state["n"] += 1
        if state["n"] > 2:
            raise ollama_service.ServiceUnavailable("down")
        return real(messages, **kw)
    ollama_service._chat = flaky
    r = client.post(f"/surveys/{s['id']}/process")
    assert r.status_code == 200
    res = client.get(f"/surveys/{s['id']}/results").json()
    assert res["status"] == "partial" and res["total_responses"] == 2 and res["failed_items"]


def test_survey_conflict_while_processing(client, project, personas, db_session=None):
    from app.database import connection
    from app.database.models import SurveyExperiment, utcnow
    s = create_survey(client, project, personas)
    with connection.SessionLocal() as db:
        row = db.get(SurveyExperiment, s["id"])
        row.status, row.processing_started_at = "processing", utcnow()
        db.commit()
    assert client.post(f"/surveys/{s['id']}/process").status_code == 409
    assert client.delete(f"/surveys/{s['id']}").status_code == 409


def test_survey_choice_prompt_and_summary(client, project, personas, ai):
    s = create_survey(client, project, personas[:1], questions=[
        {"question_text": "Pick one", "question_type": "single_choice", "options": ["Budgets", "Alerts"]}])
    client.post(f"/surveys/{s['id']}/process")
    prompt = [c for c in ai.calls if not c["json_mode"]][0]["messages"][-1]["content"]
    assert "Choose exactly ONE of: Budgets, Alerts" in prompt
    summ = client.post(f"/surveys/{s['id']}/summary").json()
    assert summ["themes"] == ["tracking", "alerts"] and "AI-generated" in summ["disclaimer"]


def test_survey_prompt_uses_only_relevant_persona_and_no_real_claims(client, project, personas, ai):
    s = create_survey(client, project, personas[:1])
    client.post(f"/surveys/{s['id']}/process")
    system = [c for c in ai.calls if not c["json_mode"]][0]["messages"][0]["content"]
    assert "Arun Kumar" in system and "Priya" not in system and "FICTIONAL" in system


def test_survey_update_replaces_questions_and_participants(client, project, personas):
    s = create_survey(client, project, personas)
    client.post(f"/surveys/{s['id']}/process")
    qid = s["questions"][0]["id"]
    upd = client.patch(f"/surveys/{s['id']}", json={
        "persona_ids": [personas[0]["id"]],
        "questions": [{"id": qid, "question_text": s["questions"][0]["question_text"]},
                      {"question_text": "Brand new question"}]}).json()
    assert upd["persona_count"] == 1 and upd["question_count"] == 2
    assert upd["response_count"] == 1 and upd["status"] == "partial"


def test_survey_history_filters_and_delete(client, project, personas):
    s1 = create_survey(client, project, personas, title="Alpha survey")
    create_survey(client, project, personas, title="Beta survey")
    client.post(f"/surveys/{s1['id']}/process")
    pid = project["id"]
    assert client.get(f"/projects/{pid}/surveys").json()["total"] == 2
    assert client.get(f"/projects/{pid}/surveys?q=alpha").json()["total"] == 1
    assert client.get(f"/projects/{pid}/surveys?status=completed").json()["items"][0]["id"] == s1["id"]
    assert client.get(f"/projects/{pid}/surveys?date_from=2999-01-01").json()["total"] == 0
    assert client.get(f"/projects/{pid}/surveys?limit=1&offset=1").json()["items"][0]["title"] == "Alpha survey"
    assert client.delete(f"/surveys/{s1['id']}").status_code == 200
    assert client.get(f"/surveys/{s1['id']}/results").status_code == 404
    assert client.get("/surveys/9999/results").status_code == 404


def test_survey_isolated_between_projects(client, project, personas):
    other = client.post("/projects/", json={"name": "Other"}).json()
    create_survey(client, project, personas)
    assert client.get(f"/projects/{other['id']}/surveys").json()["total"] == 0


# ---------------------------------------------------------------- interviews
def start_interview(client, project, persona, **over):
    r = client.post(f"/projects/{project['id']}/interviews",
                    json={"persona_id": persona["id"], "title": "Budget chat", "research_objective": "Learn", **over})
    assert r.status_code == 201, r.text
    return r.json()


def test_interview_flow_messages_ordered_and_persisted(client, project, personas, ai):
    iv = start_interview(client, project, personas[0])
    assert iv["status"] == "active" and iv["persona"]["name"] == "Arun Kumar" and iv["messages"] == []
    for text in ["First question?", "Second question?"]:
        r = client.post(f"/interviews/{iv['id']}/messages", json={"message_text": text})
        assert r.status_code == 200, r.text
    d = client.get(f"/interviews/{iv['id']}").json()
    assert [m["sequence_number"] for m in d["messages"]] == [1, 2, 3, 4]
    assert [m["role"] for m in d["messages"]] == ["researcher", "persona", "researcher", "persona"]
    assert d["message_count"] == 4
    # context: 2nd question sent with the earlier turn as history, and only this persona
    last = [c for c in ai.calls if not c["json_mode"]][-1]["messages"]
    assert [m["role"] for m in last] == ["system", "user", "assistant", "user"]
    assert "Priya" not in last[0]["content"] and "FICTIONAL" in last[0]["content"]


def test_interview_failure_does_not_save_orphan_question(client, project, personas, ai):
    iv = start_interview(client, project, personas[0])
    ai.fail_with = ollama_service.ServiceUnavailable("down")
    assert client.post(f"/interviews/{iv['id']}/messages", json={"message_text": "Hi?"}).status_code == 503
    assert client.get(f"/interviews/{iv['id']}").json()["messages"] == []


def test_interview_validation_and_wrong_project_persona(client, project, personas):
    other = client.post("/projects/", json={"name": "Other"}).json()
    r = client.post(f"/projects/{other['id']}/interviews", json={"persona_id": personas[0]["id"], "title": "x"})
    assert r.status_code == 400
    iv = start_interview(client, project, personas[0])
    assert client.post(f"/interviews/{iv['id']}/messages", json={"message_text": "   "}).status_code == 422
    assert client.post(f"/interviews/{iv['id']}/messages", json={"message_text": "x" * 5000}).status_code == 422
    assert client.post("/interviews/9999/messages", json={"message_text": "hi"}).status_code == 404
    assert client.post(f"/projects/{project['id']}/interviews", json={"persona_id": personas[0]["id"], "title": ""}).status_code == 422


def test_interview_complete_rules(client, project, personas):
    iv = start_interview(client, project, personas[0])
    assert client.post(f"/interviews/{iv['id']}/complete").status_code == 400      # nothing asked yet
    client.post(f"/interviews/{iv['id']}/messages", json={"message_text": "Hello?"})
    done = client.post(f"/interviews/{iv['id']}/complete").json()
    assert done["status"] == "completed" and done["completed_at"]
    assert client.post(f"/interviews/{iv['id']}/messages", json={"message_text": "More"}).status_code == 409
    assert client.get(f"/interviews/{iv['id']}").json()["messages"][0]["message_text"] == "Hello?"


def test_interview_history_filters_and_delete(client, project, personas):
    a = start_interview(client, project, personas[0], title="Alpha talk")
    start_interview(client, project, personas[1], title="Beta talk")
    client.post(f"/interviews/{a['id']}/messages", json={"message_text": "Q"})
    client.post(f"/interviews/{a['id']}/complete")
    pid = project["id"]
    h = client.get(f"/projects/{pid}/interviews").json()
    assert h["total"] == 2 and h["items"][1]["message_count"] == 2 and h["items"][1]["persona_name"] == "Arun Kumar"
    assert client.get(f"/projects/{pid}/interviews?status=completed").json()["total"] == 1
    assert client.get(f"/projects/{pid}/interviews?q=beta").json()["total"] == 1
    assert client.delete(f"/interviews/{a['id']}").status_code == 200
    assert client.get(f"/interviews/{a['id']}").status_code == 404


# ---------------------------------------------------------------- statistics
def test_statistics_are_project_scoped(client, project, personas):
    other = client.post("/projects/", json={"name": "Other"}).json()
    make_persona(client, other["id"], "Zed", "Doctor")
    s = create_survey(client, project, personas)
    create_survey(client, project, personas, title="never run")
    client.post(f"/surveys/{s['id']}/process")
    iv = start_interview(client, project, personas[0])
    start_interview(client, project, personas[1], title="active one")
    client.post(f"/interviews/{iv['id']}/messages", json={"message_text": "Q"})
    client.post(f"/interviews/{iv['id']}/complete")
    st = client.get(f"/projects/{project['id']}/statistics").json()
    assert (st["total_personas"], st["total_surveys"], st["completed_surveys"]) == (3, 2, 1)
    assert (st["total_interviews"], st["completed_interviews"], st["active_interviews"]) == (2, 1, 1)
    assert st["reports_generated"] == 0
    empty = client.get(f"/projects/{other['id']}/statistics").json()
    assert empty["total_personas"] == 1 and empty["completed_surveys"] == 0
    act = client.get(f"/projects/{project['id']}/activity").json()["items"]
    assert {i["type"] for i in act} == {"survey", "interview"} and len(act) == 4
    assert client.get("/projects/999/statistics").status_code == 404


# ---------------------------------------------------------------- PDF
def test_survey_pdf_contains_saved_data_and_wraps_long_text(client, project, personas, ai):
    s = create_survey(client, project, personas, title="Ünïcode ₹ survey / ../etc")
    client.post(f"/surveys/{s['id']}/process")
    long_answer = "Very long answer " * 400 + "SUPERLONGWORD" + "Z" * 200 + " END_MARKER_ZZ"
    from app.database import connection
    from app.database.models import SurveyResponse
    with connection.SessionLocal() as db:
        db.query(SurveyResponse).first().response_text = long_answer
        db.commit()
    r = client.get(f"/surveys/{s['id']}/report.pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    disp = r.headers["content-disposition"]
    assert disp.startswith('attachment; filename="synuser-survey-') and "/" not in disp and ".." not in disp
    reader = PdfReader(BytesIO(r.content))
    assert len(reader.pages) >= 2                                       # long content paginates
    text = pdf_text(r.content).replace("\n", "")
    for expected in ["Finance App", "Ünïcode", "Arun Kumar", "Priya", "Meena",
                     "Which feature would help you the most?", "END_MARKER_ZZ", "Page 2", "not real customer data"]:
        assert expected in text, expected
    assert "₹" in text
    assert client.get(f"/projects/{project['id']}/statistics").json()["reports_generated"] == 1
    reports = client.get(f"/projects/{project['id']}/reports").json()["items"]
    assert reports[0]["report_type"] == "survey" and reports[0]["survey_id"] == s["id"]


def test_survey_pdf_with_ai_summary_and_failure_note(client, project, personas, ai):
    s = create_survey(client, project, personas[:1])
    client.post(f"/surveys/{s['id']}/process")
    ok = client.get(f"/surveys/{s['id']}/report.pdf?include_summary=true")
    assert "People want simpler tracking" in pdf_text(ok.content).replace("\n", " ")
    ai.fail_with = ollama_service.ServiceUnavailable("down")
    bad = client.get(f"/surveys/{s['id']}/report.pdf?include_summary=true")
    assert bad.status_code == 200 and "X-Report-Warning".lower() in bad.headers
    assert "AI summary could not be generated" in pdf_text(bad.content).replace("\n", " ")


def test_interview_pdf_contains_transcript(client, project, personas):
    iv = start_interview(client, project, personas[0], title="Transcript <b>test</b> & more")
    for q in ["What worries you about money? " * 30 + "LAST_QUESTION_MARKER", "Second one?"]:
        client.post(f"/interviews/{iv['id']}/messages", json={"message_text": q})
    r = client.get(f"/interviews/{iv['id']}/report.pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    text = pdf_text(r.content).replace("\n", "")
    for expected in ["Finance App", "Arun Kumar", "LAST_QUESTION_MARKER", "Second one?", "Simulated answer", "Transcript"]:
        assert expected in text, expected
    assert "<b>" in text                                              # user markup is escaped, not interpreted


def test_pdf_invalid_ids_and_empty_data(client, project, personas):
    assert client.get("/surveys/9999/report.pdf").status_code == 404
    assert client.get("/interviews/9999/report.pdf").status_code == 404
    s = create_survey(client, project, personas)                      # never processed
    r = client.get(f"/surveys/{s['id']}/report.pdf")
    assert r.status_code == 200 and "No responses saved" in pdf_text(r.content)


# ---------------------------------------------------------------- Ollama service + DB errors
def test_ollama_connection_error_maps_to_503(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(httpx, "post", boom)
    monkeypatch.undo()          # restore fixtures' patches, then patch httpx only
    monkeypatch.setattr(httpx, "post", boom)
    from app.services.ollama_service import _chat
    with pytest.raises(ollama_service.ServiceUnavailable) as e:
        _chat([{"role": "user", "content": "x"}], json_mode=False, temperature=0, max_tokens=5)
    assert e.value.code == "ollama_unavailable"


def test_ollama_status_reports_missing_model(monkeypatch):
    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"models": [{"name": "llama3:8b"}]}
    monkeypatch.undo()
    monkeypatch.setattr(httpx, "get", lambda *a, **k: R())
    st = ollama_service.status()
    assert st["reachable"] and not st["model_installed"] and "ollama pull" in st["detail"]


def test_extract_json_handles_fences_and_think_blocks():
    raw = '<think>hmm</think>```json\n{"a": 1}\n```'
    assert ollama_service._extract_json(raw) == {"a": 1}
    assert ollama_service._extract_json('Sure! {"a": 2} done') == {"a": 2}


def test_database_unavailable_returns_503_not_traceback(client, project, monkeypatch):
    from sqlalchemy.exc import OperationalError
    from app.database import connection

    class Broken:
        def __enter__(self): raise OperationalError("SELECT 1", {}, Exception("Can't connect"))
        def __exit__(self, *a): pass
        def connect(self): return self
    monkeypatch.setattr(connection, "engine", Broken())
    h = client.get("/health/database")
    assert h.status_code == 503 and h.json()["connected"] is False and "MySQL" in h.json()["detail"]
    assert "Traceback" not in h.text


def test_validation_error_format_is_consistent(client):
    r = client.post("/projects/", json={"name": ""})
    assert r.status_code == 422 and r.json()["code"] == "validation_error" and isinstance(r.json()["detail"], str)


def test_legacy_routes_still_work(client, project, personas):
    s = client.post("/surveys/", json={"project_id": project["id"], "title": "Legacy"}).json()
    q = client.post(f"/surveys/{s['id']}/questions", json={"question_text": "Old style?"}).json()
    assert q["question_order"] == 1
    r = client.post(f"/surveys/{s['id']}/generate-responses").json()
    assert r["total_responses"] == 3
    res = client.get(f"/surveys/{s['id']}/results").json()
    assert res["results"][0]["question"] == "Old style?" and res["results"][0]["answers"][0]["answer"]
    iv = client.post("/interviews/", json={"project_id": project["id"], "persona_id": personas[0]["id"], "title": "Old"}).json()
    assert client.post(f"/interviews/{iv['id']}/messages", json={"message_text": "hi"}).status_code == 200
    assert len(client.get(f"/interviews/{iv['id']}/messages").json()) == 2
    legacy_gen = client.post(f"/personas/generate/{project['id']}").json()
    assert legacy_gen["persona"]["name"] and legacy_gen["behavior"]["saving_habit"] == 3


def test_interview_summary_endpoint(client, project, personas):
    iv = start_interview(client, project, personas[0])
    assert client.post(f"/interviews/{iv['id']}/summary").status_code == 400      # no transcript yet
    client.post(f"/interviews/{iv['id']}/messages", json={"message_text": "Q?"})
    r = client.post(f"/interviews/{iv['id']}/summary").json()
    assert r["needs"] == ["clarity"] and "AI-generated" in r["disclaimer"]
