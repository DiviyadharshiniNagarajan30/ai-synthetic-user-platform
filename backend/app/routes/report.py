"""PDF downloads for surveys and interviews. Rendered on demand from saved records."""
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import Report
from app.errors import AppError
from app.services import interview_service, report_service, survey_service
from app.services.common import get_interview_or_404, get_survey_or_404

router = APIRouter(tags=["PDF Reports"])


def _pdf_response(content: bytes, filename: str, warning: str | None) -> Response:
    headers = {"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store",
               "Access-Control-Expose-Headers": "Content-Disposition, X-Report-Warning"}
    if warning:
        headers["X-Report-Warning"] = warning[:200].encode("ascii", "ignore").decode()
    return Response(content=content, media_type="application/pdf", headers=headers)


@router.get("/surveys/{survey_id}/report.pdf")
def survey_report(survey_id: int, include_summary: bool = Query(False), db: Session = Depends(get_db)):
    survey = get_survey_or_404(db, survey_id)
    results = survey_service.build_results(db, survey)
    ai, note = None, None
    if include_summary:
        try:
            ai = survey_service.summarize_with_ai(db, survey)
        except AppError as exc:
            note = f"AI summary could not be generated: {exc.detail}"
    pdf = report_service.survey_pdf(results, ai, note)
    filename = report_service.safe_filename(survey.title, "survey", survey.id)
    db.add(Report(project_id=survey.project_id, report_type="survey", survey_id=survey.id, filename=filename))
    db.commit()
    return _pdf_response(pdf, filename, note)


@router.get("/interviews/{interview_id}/report.pdf")
def interview_report(interview_id: int, include_summary: bool = Query(False), db: Session = Depends(get_db)):
    session = get_interview_or_404(db, interview_id)
    detail = interview_service.detail(db, session)
    ai, note = None, None
    if include_summary:
        try:
            ai = interview_service.summarize_with_ai(db, session)
        except AppError as exc:
            note = f"AI summary could not be generated: {exc.detail}"
    pdf = report_service.interview_pdf(detail, ai, note)
    filename = report_service.safe_filename(session.title, "interview", session.id)
    db.add(Report(project_id=session.project_id, report_type="interview", interview_id=session.id, filename=filename))
    db.commit()
    return _pdf_response(pdf, filename, note)
