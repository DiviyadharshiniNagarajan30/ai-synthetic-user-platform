# SynUser — AI Research Studio

AI-powered **synthetic users** for product research: generate personas, run surveys, interview a persona,
keep everything in MySQL, and download PDF reports. All personas and answers are **AI-generated simulations** —
not genuine customer feedback and not statistically representative market research.

Stack: vanilla HTML/CSS/JS frontend · FastAPI + SQLAlchemy + PyMySQL · MySQL/MariaDB · Ollama (`qwen3:1.7b`) · ReportLab.

```
frontend/                 static app (index.html, assets/css, assets/js/*.js — no build step)
backend/app/              main.py, config.py, errors.py, database/ (models, migrate), routes/, schemas/, services/, tests/
backend/.env.example      configuration template (copy to backend/.env; never commit .env)
tests/e2e/                browser end-to-end test (Playwright) + stand-in Ollama for machines without a model
```

## 1. Setup (Windows PowerShell)

**MySQL (XAMPP):** open the XAMPP Control Panel → *Start* MySQL. Note its port (shown next to the module; 3306 by
default, sometimes 3307). Create the empty database once (phpMyAdmin → *SQL*, or `mysql -u root -p`):

```sql
CREATE DATABASE IF NOT EXISTS synthetic_user_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

**Ollama:** install from ollama.com, then:

```powershell
ollama pull qwen3:1.7b
ollama list            # confirm qwen3:1.7b is listed
```

**Backend:**

```powershell
cd F:\ai-synthetic-user-platform\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
pip install -r requirements.txt
Copy-Item .env.example .env           # then edit .env: set the password and the MySQL port
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

API docs: <http://127.0.0.1:8000/docs> · health: `/health`, `/health/database`, `/health/ollama`.

**Frontend** (separate PowerShell window, from the folder that *contains* `frontend`):

```powershell
cd F:\ai-synthetic-user-platform
python -m http.server 5500
```

Open <http://localhost:5500/frontend/>. If your backend is not on `http://127.0.0.1:8000`, click the ⚙ icon in the
sidebar and change the API URL (stored in the browser). Allowed browser origins are set by `FRONTEND_ORIGIN` in `.env`.

### Configuration (`backend/.env`)

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | – | `mysql+pymysql://root:PASSWORD@127.0.0.1:3306/synthetic_user_db` (use your real port) |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama endpoint |
| `OLLAMA_MODEL` | `qwen3:1.7b` | Model name |
| `OLLAMA_TIMEOUT_SECONDS` | `180` | Per model call |
| `FRONTEND_ORIGIN` | `http://localhost:5500` | Comma separated CORS origins |
| `MAX_PERSONAS_PER_REQUEST` | `20` | Generation cap per request |

### Upgrading an existing database (your current data is kept)
The backend runs `app/database/migrate.py` at startup. It **creates missing tables, adds missing columns** (nullable),
**back-fills** them (survey status, survey participants from existing answers, interview message numbering) and adds
unique indexes (one answer per question+persona, unique message numbers). It never drops, renames or truncates
anything and is safe to re-run. If old duplicate answers exist, the index is skipped with a warning in the log; remove
the duplicates and restart. `create_all` alone cannot add columns to existing tables, which is why this step exists.
No database is created or overwritten automatically.

## 2. Using it

1. **New project** (sidebar) → it is selected automatically (selection persists across refreshes).
2. **Persona Generation → Generate**: choose occupations (or type a custom profession), age/income ranges, etc.
   Personas are saved to MySQL; **History** shows each run with its criteria; **Report** summarises them (CSV export).
3. **Survey → Generate**: add questions (open-ended, single/multiple choice, rating), pick personas, **Process survey**.
   Answers are saved one by one and appear below the button; failures are listed with a **Retry failed responses**
   button (processing is idempotent — only missing answers are generated). **History** reopens any survey from the
   database; **Report** previews and downloads a PDF (optionally with an AI summary).
4. **Interview → Start Interview**: pick one persona, chat, **End interview** when finished. Each question/answer pair
   is saved only after the model replies; transcripts survive refreshes; history can resume active interviews or view
   completed ones; PDF includes the full transcript.
5. **Overview** shows live counts for the selected project: personas, completed surveys (status `completed`),
   completed interviews (explicitly ended), reports generated (PDF downloads), plus latest sessions and activity.

## 3. API summary
(See `/docs` for schemas.)

| Area | Routes |
|---|---|
| Health | `GET /health`, `/health/database`, `/health/ollama` |
| Projects | `GET/POST /projects/`, `GET/PATCH/DELETE /projects/{id}` (`?force=true` to delete with research), `GET /projects/{id}/statistics`, `/activity`, `/reports` |
| Personas | `GET/POST /projects/{id}/personas`, `POST /projects/{id}/personas/generate`, `GET /projects/{id}/persona-generations`, `GET /persona-generations/{id}`, `GET/PATCH/DELETE /personas/{id}` |
| Surveys | `POST/GET /projects/{id}/surveys`, `GET/PATCH/DELETE /surveys/{id}`, `POST /surveys/{id}/process`, `GET /surveys/{id}/results`, `POST /surveys/{id}/summary`, `GET /surveys/{id}/report.pdf[?include_summary=true]` |
| Interviews | `POST/GET /projects/{id}/interviews`, `GET/DELETE /interviews/{id}`, `POST /interviews/{id}/messages`, `GET /interviews/{id}/messages`, `POST /interviews/{id}/complete`, `POST /interviews/{id}/summary`, `GET /interviews/{id}/report.pdf[?include_summary=true]` |
| Legacy (kept) | `POST /surveys/`, `POST/GET /surveys/{id}/questions`, `POST /surveys/{id}/generate-responses`, `GET /surveys/{id}/insights`, `POST /interviews/`, `POST/GET /personas/`, `POST /personas/generate/{project_id}`, `GET/POST /behaviors/…`, `GET /reports/{project_id}` and `/pdf` (project-wide AI analysis) |

Errors are JSON `{"detail": "...", "code": "..."}`: 404 missing, 422 invalid input, 409 conflicts (e.g. survey already
processing, deleting non-empty projects), 503 database/Ollama unavailable, 502 unusable model output.

## 4. Tests
```powershell
cd backend
pytest app/tests -q                       # 44 tests, in-memory SQLite, model mocked
$env:TEST_DATABASE_URL="mysql+pymysql://user:pass@127.0.0.1:3306/synuser_test"; pytest app/tests -q   # optional: real MySQL (DB name must contain "test"; tables are dropped!)
```
Browser end-to-end (needs `pip install playwright pypdf && playwright install chromium`, a MySQL and bash): `bash tests/e2e/run_e2e.sh`.
The e2e run uses a **stand-in Ollama** with canned answers — it verifies the application, not model quality.

## 5. Troubleshooting
* **"Database cannot be reached"** – start MySQL in XAMPP; confirm the port in the XAMPP panel matches `DATABASE_URL`; check user/password; the database in `DATABASE_URL` must exist.
* **"Local AI service is unavailable"** – start Ollama (`ollama serve` or the tray app); `curl http://127.0.0.1:11434/api/tags`.
* **"Model … is not installed"** – `ollama pull qwen3:1.7b` (or change `OLLAMA_MODEL`).
* **Browser says "Cannot reach the backend"** – start uvicorn; check the API URL under ⚙; check `FRONTEND_ORIGIN` matches the page origin.
* **Slow generation** – a 1.7B model on CPU can take 10–60 s per persona/answer; large surveys take minutes (answers appear as they are saved).
* **Survey stuck on "processing"** after a backend crash – it is automatically treated as abandoned after 30 minutes (`STALE_PROCESSING_MINUTES`); processing again resumes.

## 6. Known limitations
* No authentication: designed as a local single-researcher tool. Do not expose it to the internet as-is.
* Generation/processing are synchronous requests (progress for surveys is polled from saved rows; persona generation shows a busy indicator only).
* Persona "regenerate" is not implemented (generate new personas and delete old ones).
* PDF font (DejaVu Sans) covers Latin, Cyrillic, Greek and ₹; Tamil/Devanagari/CJK text will not render in PDFs.
* Choice/rating answers are free text produced by the model following an instruction; they are not machine-validated against the options.
* Small local models can produce repetitive answers; duplicate personas are rejected, repeated survey answers are not.
