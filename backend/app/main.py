import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError, InterfaceError

from app import config
from app.database import connection
from app.database import models  # noqa: F401  (register SQLAlchemy models)
from app.database.migrate import run_migrations
from app.errors import AppError
from app.routes import behavior, interview, persona, project, report, report_legacy, survey
from app.services import ollama_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("synuser")

DB_HELP = ("The database cannot be reached. Check that MySQL is running and that the host, port and "
           "credentials in DATABASE_URL are correct (XAMPP often uses port 3306, sometimes 3307).")
startup_state = {"migration": None, "database_error": None}


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Never crash on a missing database: report it via /health/database instead."""
    if connection.engine is None:
        startup_state["database_error"] = "DATABASE_URL is not set"
        logger.error("DATABASE_URL is not set - copy .env.example to backend/.env")
    else:
        try:
            startup_state["migration"] = run_migrations(connection.engine)
            logger.info("Database ready: %s", connection.safe_database_label())
        except Exception as exc:  # noqa: BLE001
            startup_state["database_error"] = type(exc).__name__
            logger.error("Database startup check failed (%s) for %s", type(exc).__name__,
                         connection.safe_database_label())
    yield


app = FastAPI(title="SynUser - AI Research Studio API",
              description="Synthetic personas, surveys, interviews and PDF reports for product research. "
                          "All personas and responses are AI-generated simulations.",
              version="2.0.0", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=config.allowed_origins(), allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["Content-Disposition", "X-Report-Warning"])


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "code": exc.code, **exc.extra})


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    parts = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err["loc"] if x not in ("body", "query", "path"))
        msg = err["msg"].removeprefix("Value error, ")
        parts.append(f"{loc}: {msg}" if loc else msg)
    return JSONResponse(status_code=422, content={"detail": "; ".join(parts) or "Invalid input",
                                                  "code": "validation_error"})


@app.exception_handler(OperationalError)
@app.exception_handler(InterfaceError)
async def db_down_handler(_: Request, exc: DBAPIError):
    logger.error("Database error: %s", type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": DB_HELP, "code": "database_unavailable"})


@app.exception_handler(Exception)
async def unexpected_handler(_: Request, exc: Exception):
    logger.exception("Unhandled error")
    return JSONResponse(status_code=500, content={"detail": "Unexpected server error. See the backend log.",
                                                  "code": "internal_error"})


for module in (project, persona, survey, interview, report, report_legacy):
    app.include_router(module.router)
app.include_router(behavior.router)


@app.get("/", tags=["Health"])
def home():
    return {"message": "SynUser API running", "docs": "/docs"}


def _database_status() -> dict:
    if connection.engine is None:
        return {"connected": False, "detail": "DATABASE_URL is not set."}
    try:
        with connection.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"connected": True, "target": connection.safe_database_label(), "detail": "ok",
                "migration": startup_state["migration"]}
    except Exception as exc:  # noqa: BLE001
        return {"connected": False, "target": connection.safe_database_label(),
                "detail": f"{DB_HELP} ({type(exc).__name__})"}


@app.get("/health", tags=["Health"])
def health():
    db = _database_status()
    return {"status": "ok" if db["connected"] else "degraded", "api": True, "database": db["connected"],
            "model": config.OLLAMA_MODEL, "income_currency": "INR"}


@app.get("/health/database", tags=["Health"])
def health_database():
    return JSONResponse(status_code=200 if (s := _database_status())["connected"] else 503, content=s)


@app.get("/health/ollama", tags=["Health"])
def health_ollama():
    s = ollama_service.status()
    return JSONResponse(status_code=200 if s["reachable"] and s["model_installed"] else 503, content=s)
