"""Browser-driven end-to-end test of the real frontend against the real backend + MySQL."""
import os, re, subprocess, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]
SHOTS = Path(os.getenv("E2E_SHOTS", "/tmp/shots")); SHOTS.mkdir(exist_ok=True, parents=True)
URL = "http://localhost:5500/frontend/"
results, console_errors = [], []

def step(name):
    def deco(fn):
        try:
            fn(); results.append((name, True, ""))
            print(f"PASS  {name}")
        except Exception as e:  # noqa
            results.append((name, False, str(e)[:400])); print(f"FAIL  {name}\n      {str(e)[:400]}")
            try: PAGE.screenshot(path=str(SHOTS / f"FAIL-{re.sub('[^a-z0-9]+','-',name.lower())}.png"))
            except Exception: pass
        return fn
    return deco

def pdf_text(path): return " ".join(" ".join(p.extract_text().split()) for p in PdfReader(path).pages)
def start_backend():
    subprocess.Popen("cd %s/backend && nohup python3 -m uvicorn app.main:app --port 8000 >>/tmp/uvicorn.log 2>&1 &" % ROOT, shell=True)
    for _ in range(40):
        if subprocess.run("curl -sf localhost:8000/health", shell=True, capture_output=True).returncode == 0: return
        time.sleep(0.5)
def stop_backend(): subprocess.run("pkill -f 'uvicorn app[.]main'", shell=True); time.sleep(1)

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1366, "height": 900}, accept_downloads=True)
    PAGE = ctx.new_page()
    PAGE.on("console", lambda m: m.type == "error" and not any(x in m.text for x in ("fonts.g", "ERR_", "Failed to load resource")) and console_errors.append(m.text))
    PAGE.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))
    P = PAGE

    @step("1. empty database shows the 'create a project' state")
    def _():
        P.goto(URL); expect(P.locator("#noProject")).to_contain_text("Create a project to begin your research.")
        expect(P.locator("#statusList")).to_contain_text("Database: connected"); expect(P.locator("#statusList")).to_contain_text("Local AI: qwen3:1.7b")
        P.screenshot(path=str(SHOTS / "01-empty.png"))

    @step("2. create a project; it is selected and listed in the sidebar")
    def _():
        P.click("#newProjectBtn")
        P.fill(".modal-card input >> nth=0", "AI Personal Finance and Budgeting App")
        P.fill(".modal-card textarea >> nth=0", "Expense tracking, budgets, savings goals and an AI assistant")
        P.click(".modal-card button[type=submit]")
        expect(P.locator(".project-item.active .pname")).to_have_text("AI Personal Finance and Budgeting App")
        expect(P.locator("#projectPill")).to_have_text("AI Personal Finance and Budgeting App")
        expect(P.locator("#ovName")).to_have_text("AI Personal Finance and Budgeting App")
        expect(P.locator("#ovMetrics .metric-card").first.locator("strong")).to_have_text("0")
        expect(P.locator("#ovActivity")).to_contain_text("No research activity yet")

    @step("3. sidebar navigation + contextual top tabs")
    def _():
        for page, tabs in {"personas": ["Generate", "History", "Report"], "survey": ["Generate", "History", "Report"], "interview": ["Start Interview", "History", "Report"], "overview": ["Dashboard"]}.items():
            P.click(f".side-link[data-page={page}]")
            assert P.locator("#topTabs .nav-tab").all_inner_texts() == tabs, (page, P.locator("#topTabs .nav-tab").all_inner_texts())
            expect(P.locator(f".side-link[data-page={page}]")).to_have_class(re.compile("active"))
        P.click(".side-link[data-page=survey]"); P.click("#topTabs .nav-tab:has-text('History')")
        expect(P.locator("#shList")).to_contain_text("No surveys have been created for this project yet.")
        assert P.url.endswith("#/survey/history")

    @step("4. generate personas (diverse occupations) via the local model service")
    def _():
        P.click(".side-link[data-page=personas]")
        expect(P.locator("#plGrid")).to_contain_text("Generate synthetic personas for this project before starting")
        P.click(".chip:has-text('Teacher')"); P.click(".chip:has-text('Accountant')"); P.fill("#pgCustomOcc", "Farmer")
        P.fill("#pgCount", "3"); P.fill("#pgAgeMin", "25"); P.fill("#pgAgeMax", "60")
        P.click("#pgSubmit")
        expect(P.locator("#pgResult")).to_contain_text("Generated 3 of 3 persona(s)", timeout=30000)
        expect(P.locator("#plGrid .persona-card")).to_have_count(3)
        occ = P.locator("#plGrid .persona-card .role").all_inner_texts()
        assert any("Teacher" in o for o in occ) and any("Accountant" in o for o in occ) and any("Farmer" in o for o in occ), occ
        expect(P.locator("#plGrid .synthetic-tag").first).to_have_text("Synthetic")
        P.screenshot(path=str(SHOTS / "02-personas.png"), full_page=True)

    @step("5. persona search, filter, details, edit")
    def _():
        P.fill("#plSearch", "Farmer"); expect(P.locator("#plGrid .persona-card")).to_have_count(1)
        P.fill("#plSearch", ""); expect(P.locator("#plGrid .persona-card")).to_have_count(3)
        P.select_option("#plOccupation", "Teacher"); expect(P.locator("#plGrid .persona-card")).to_have_count(1)
        P.select_option("#plOccupation", ""); expect(P.locator("#plGrid .persona-card")).to_have_count(3)
        P.locator("#plGrid .persona-card button:has-text('View details')").first.click()
        expect(P.locator(".modal-card")).to_contain_text("AI-generated synthetic persona")
        P.click(".modal-card button:has-text('Edit')"); P.fill(".modal-card form label:has-text('Location') input", "Madurai, India")
        P.click(".modal-card button[type=submit]"); expect(P.locator(".toast:has-text('Persona updated.')")).to_be_visible()
        expect(P.locator("#plGrid .persona-card .role").first).to_contain_text(re.compile("Madurai|Chennai"))

    @step("6. persona generation history shows criteria + personas")
    def _():
        P.click("#topTabs .nav-tab:has-text('History')")
        expect(P.locator("#pghList")).to_contain_text("3 of 3 personas"); expect(P.locator("#pghList")).to_contain_text("Farmer")
        P.click("#pghList button:has-text('View 3 persona')"); expect(P.locator("#pghList .persona-card")).to_have_count(3)
        P.click("#topTabs .nav-tab:has-text('Report')"); expect(P.locator("#prBody")).to_contain_text("By occupation")

    @step("7. build a survey, process it, results render below the button")
    def _():
        P.click(".side-link[data-page=survey]")
        P.fill("#svTitle", "Expense tracking survey"); P.fill("#svTopic", "Budgeting"); P.fill("#svObjective", "Find the biggest budgeting pains")
        P.fill("#svQuestions input[aria-label='Question 1']", "What is your biggest challenge in managing monthly expenses?")
        P.click("#svAddQ"); P.fill("#svQuestions input[aria-label='Question 2']", "Which feature would help you the most?")
        P.click("#svSelectAll"); expect(P.locator("#svPersonaCount")).to_have_text("3 of 3 selected")
        P.click("#svQuestions .q-row >> nth=1 >> button[title='Move up']")          # reorder
        assert P.input_value("#svQuestions input[aria-label='Question 1']").startswith("Which feature")
        P.click("#svQuestions .q-row >> nth=0 >> button[title='Move down']")
        P.click("#svProcess")
        expect(P.locator("#svProcess")).to_be_disabled()
        expect(P.locator("#svResults .q-result")).to_have_count(2, timeout=30000)
        expect(P.locator("#svResults .badge.completed")).to_be_visible(timeout=40000)
        expect(P.locator("#svResults .answer")).to_have_count(6)
        txt = P.inner_text("#svResults")
        assert "Question 1: What is your biggest challenge" in txt and re.search(r"Persona 1 — \w+ \w+, \w+", txt), txt[:400]
        assert "6 of 6 responses saved" in txt and "AI-generated synthetic research" in txt
        # results are located BELOW the Process button
        assert P.locator("#svProcess").bounding_box()["y"] < P.locator("#svResults").bounding_box()["y"]
        P.screenshot(path=str(SHOTS / "03-survey-results.png"), full_page=True)

    @step("8. survey results survive a browser refresh")
    def _():
        P.reload(); expect(P.locator("#svResults .q-result")).to_have_count(2, timeout=15000)
        expect(P.locator("#svResults .answer")).to_have_count(6); expect(P.locator("#svTitle")).to_have_value("Expense tracking survey")

    @step("9. survey history lists it, reopens from the backend, and exports a real PDF")
    def _():
        P.click("#topTabs .nav-tab:has-text('History')")
        row = P.locator("#shList .list-row"); expect(row).to_have_count(1)
        expect(row).to_contain_text("2 questions · 3 personas · 6/6 responses"); expect(row.locator(".badge")).to_have_text("completed")
        with P.expect_download() as dl: row.locator("button:has-text('Download PDF')").click()
        d = dl.value; path = SHOTS / d.suggested_filename; d.save_as(path)
        assert d.suggested_filename.startswith("synuser-survey-1-") and path.read_bytes()[:5] == b"%PDF-"
        text = pdf_text(path)
        for needle in ["Expense tracking survey", "AI Personal Finance and Budgeting App", "Which feature would help you the most?", "As ", "Find the biggest budgeting pains"]:
            assert needle in text, needle
        P.click("#shList button:has-text('View results')"); expect(P.locator("#svResults .answer")).to_have_count(6, timeout=10000)

    @step("10. survey report tab: preview, AI summary, PDF with summary")
    def _():
        P.click("#topTabs .nav-tab:has-text('Report')")
        expect(P.locator("#srBody")).to_contain_text("Project details", timeout=10000); expect(P.locator("#srBody")).to_contain_text("Participating personas")
        P.click("#srBody button:has-text('Generate AI summary')"); expect(P.locator("#srBody")).to_contain_text("AI-generated summary", timeout=20000)
        P.check("#srSummary")
        with P.expect_download() as dl: P.click("#srBody button:has-text('Download PDF')")
        d = dl.value; path = SHOTS / "survey-summary.pdf"; d.save_as(path)
        assert "Participants want automatic tracking" in pdf_text(path)

    @step("11. interview: start, chat, answers saved in order")
    def _():
        P.click(".side-link[data-page=interview]")
        expect(P.locator("#ivProfile")).to_contain_text("Synthetic")
        P.fill("#ivTitle", "Budgeting habits interview"); P.fill("#ivObjective", "Understand tracking habits")
        P.click("#ivStart"); expect(P.locator("#ivChat .chat-card")).to_be_visible()
        P.fill("#ivInput", "How do you track your spending today?"); P.press("#ivInput", "Enter")
        expect(P.locator(".msg.persona:not(.pending)")).to_have_count(1, timeout=15000)
        P.fill("#ivInput", "What would make you trust an AI assistant?"); P.press("#ivInput", "Enter")
        expect(P.locator(".msg.persona:not(.pending)")).to_have_count(2, timeout=15000)
        roles = P.locator("#ivMessages .msg").evaluate_all("els => els.map(e => e.className.split(' ')[1])")
        assert roles == ["researcher", "persona", "researcher", "persona"], roles
        expect(P.locator("#ivSave")).to_contain_text("Saved at")
        P.screenshot(path=str(SHOTS / "04-interview.png"), full_page=True)

    @step("12. interview transcript survives a refresh")
    def _():
        P.reload(); expect(P.locator("#ivMessages .msg")).to_have_count(4, timeout=15000)
        expect(P.locator("#ivMessages")).to_contain_text("How do you track your spending today?")

    @step("13. failed AI reply: nothing half-saved, question kept for retry")
    def _():
        open("/tmp/fake_ollama_fail", "w").close()
        try:
            P.fill("#ivInput", "This one will fail?"); P.press("#ivInput", "Enter")
            expect(P.locator("#notice")).to_be_visible(timeout=15000); expect(P.locator("#notice")).to_contain_text("local AI service returned an error")
            expect(P.locator("#ivMessages .msg")).to_have_count(4); expect(P.locator("#ivInput")).to_have_value("This one will fail?")
            expect(P.locator("#ivSave")).to_have_text("Not saved")
        finally: os.remove("/tmp/fake_ollama_fail")
        P.press("#ivInput", "Enter"); expect(P.locator(".msg.persona:not(.pending)")).to_have_count(3, timeout=15000)

    @step("14. end the interview; it becomes read-only and completed")
    def _():
        P.click("#ivEnd"); P.click(".modal-card button:has-text('End interview')")
        expect(P.locator("#ivChat .badge.completed")).to_be_visible(); expect(P.locator("#ivInput")).to_be_disabled()
        expect(P.locator("#ivMessages .msg")).to_have_count(6)

    @step("15. interview history + PDF contains the full transcript")
    def _():
        P.click("#topTabs .nav-tab:has-text('History')")
        row = P.locator("#ihList .list-row"); expect(row).to_have_count(1); expect(row).to_contain_text("6 messages"); expect(row.locator(".badge")).to_have_text("completed")
        with P.expect_download() as dl: row.locator("button:has-text('Download PDF')").click()
        d = dl.value; path = SHOTS / d.suggested_filename; d.save_as(path)
        text = pdf_text(path)
        for needle in ["Budgeting habits interview", "How do you track your spending today?", "What would make you trust an AI assistant?", "This one will fail?", "Persona profile"]:
            assert needle in text, needle
        row.locator("button:has-text('View transcript')").click(); expect(P.locator("#ivMessages .msg")).to_have_count(6, timeout=10000)
        P.click("#topTabs .nav-tab:has-text('Report')"); expect(P.locator("#irBody")).to_contain_text("Transcript", timeout=10000)

    @step("16. dashboard counts come from the backend and update")
    def _():
        P.click(".side-link[data-page=overview]")
        expect(P.locator("#ovMetrics")).to_contain_text("Completed surveys", timeout=10000)
        vals = {c.locator(".metric-label").inner_text(): c.locator("strong").inner_text() for c in P.locator("#ovMetrics .metric-card").all()}
        assert vals == {"Synthetic personas": "3", "Completed surveys": "1", "Completed interviews": "1", "Reports generated": "3"}, vals
        expect(P.locator("#ovSurveys")).to_contain_text("Expense tracking survey"); expect(P.locator("#ovInterviews")).to_contain_text("Budgeting habits interview")
        P.screenshot(path=str(SHOTS / "05-overview.png"), full_page=True)

    @step("17. project switching is isolated and the selection persists")
    def _():
        P.click("#newProjectBtn"); P.fill(".modal-card input >> nth=0", "Second project"); P.click(".modal-card button[type=submit]")
        expect(P.locator("#projectPill")).to_have_text("Second project")
        expect(P.locator("#ovMetrics .metric-card").first.locator("strong")).to_have_text("0")
        P.click(".side-link[data-page=survey]"); expect(P.locator("#svPersonas")).to_contain_text("Generate synthetic personas for this project")
        expect(P.locator("#svResults .q-result")).to_have_count(0)
        P.click(".side-link[data-page=interview]"); expect(P.locator("#ivChat")).to_be_hidden(); expect(P.locator("#ivProfile")).to_contain_text("Generate synthetic personas")
        P.reload(); expect(P.locator("#projectPill")).to_have_text("Second project")
        P.click(".project-item:has-text('AI Personal Finance') .pname"); P.click(".side-link[data-page=personas]")
        expect(P.locator("#plGrid .persona-card")).to_have_count(3)

    @step("18. deleting a non-empty project requires explicit confirmation of cascade")
    def _():
        P.click(".project-item:has-text('Second project') .pbtn[title='Delete project']"); P.click(".modal-card button:has-text('Delete project')")
        expect(P.locator(".project-item")).to_have_count(1, timeout=10000)
        P.click(".project-item .pbtn[title='Delete project']"); P.click(".modal-card button:has-text('Delete project')")
        expect(P.locator(".modal-card")).to_contain_text("Delete project and all its research?")
        P.click(".modal-card button:has-text('Cancel')"); expect(P.locator(".project-item")).to_have_count(1)

    @step("19. history survives a backend restart")
    def _():
        stop_backend(); start_backend()
        P.reload(); P.click(".side-link[data-page=survey]"); P.click("#topTabs .nav-tab:has-text('History')")
        expect(P.locator("#shList .list-row")).to_have_count(1, timeout=15000)
        P.click(".side-link[data-page=interview]"); P.click("#topTabs .nav-tab:has-text('History')")
        expect(P.locator("#ihList .list-row")).to_have_count(1, timeout=15000)

    @step("20. backend unreachable: clear error, no fake empty data")
    def _():
        stop_backend(); P.reload()
        expect(P.locator("#notice")).to_contain_text("Cannot reach the backend", timeout=15000)
        expect(P.locator("#noProject")).to_contain_text("could not be loaded"); expect(P.locator("#statusList")).to_contain_text("API: unreachable")
        P.screenshot(path=str(SHOTS / "06-backend-down.png"))
        start_backend(); P.click("#noProject button:has-text('Try again')")
        expect(P.locator(".project-item")).to_have_count(1, timeout=15000)
        expect(P.locator("#notice")).to_be_hidden()          # stale error banner must clear once reconnected
        box = P.locator(".project-item .pbtn").first.bounding_box(); assert box and box["x"] + box["width"] <= 256, box   # edit/delete buttons visible inside sidebar

    @step("21. mobile layout has no horizontal overflow")
    def _():
        P.set_viewport_size({"width": 390, "height": 800}); P.click(".side-link[data-page=survey]") if P.locator("#sidebar.open").count() else None
        P.goto(URL + "#/survey/generate"); expect(P.locator("#svResults .q-result")).to_have_count(2, timeout=15000)
        over = P.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth"); assert over <= 1, f"overflow {over}px"
        P.screenshot(path=str(SHOTS / "07-mobile-survey.png"), full_page=True)
        P.goto(URL + "#/overview/dashboard"); over = P.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth"); assert over <= 1, over

    @step("22. no unexpected console or page errors")
    def _():
        assert not console_errors, console_errors[:5]

    browser.close()

failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)}/{len(results)} browser steps passed")
sys.exit(1 if failed else 0)
