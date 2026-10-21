
import json
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from ..services import ollama_service

from ..database.connection import get_db
from ..database.models import (
    Project,
    Persona,
    SurveyExperiment,
    SurveyQuestion,
    SurveyResponse as SurveyResponseModel,
    InterviewSession,
    InterviewMessage,
)
from ..schemas.report import ResearchReportResponse

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

router = APIRouter(prefix="/reports", tags=["Project Research Report (AI analysis)"])



@router.get(
    "/{project_id}",
    response_model=ResearchReportResponse,
)
def generate_research_report(
    project_id: int,
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(
        Project.id == project_id
    ).first()

    if not project:
        raise HTTPException(
            status_code=404,
            detail="Project not found",
        )

    personas = db.query(Persona).filter(
        Persona.project_id == project_id
    ).all()

    surveys = db.query(SurveyExperiment).filter(
        SurveyExperiment.project_id == project_id
    ).all()

    survey_findings = []
    common_themes = []
    sentiment_summary = {}
    persona_interests = []
    total_responses = 0

    for survey in surveys:
        questions = db.query(SurveyQuestion).filter(
            SurveyQuestion.survey_id == survey.id
        ).all()

        question_ids = [q.id for q in questions]

        if question_ids:
            total_responses += db.query(
                SurveyResponseModel
            ).filter(
                SurveyResponseModel.question_id.in_(question_ids)
            ).count()

        survey_findings.append(
            f"Survey '{survey.title}' contains "
            f"{len(questions)} questions."
        )

    interview_sessions = db.query(InterviewSession).filter(
        InterviewSession.project_id == project_id
    ).all()

    interview_messages = []
    interview_findings = []

    for session in interview_sessions:
        messages = db.query(InterviewMessage).filter(
            InterviewMessage.session_id == session.id
        ).order_by(InterviewMessage.id.asc()).all()

        for message in messages:
            interview_messages.append({
                "persona_id": session.persona_id,
                "role": message.role,
                "message": message.message_text,
            })

    if not surveys and not interview_messages:
        raise HTTPException(
            status_code=400,
            detail=(
                "No survey or interview data exists for this project yet."
            ),
        )

    prompt_data = {
        "project": {
            "name": project.name,
            "product_description": project.product_description,
            "target_market": project.target_market,
            "research_objective": project.research_objective,
        },
        "personas": [
            {
                "id": p.id,
                "name": p.name,
                "occupation": p.occupation,
                "goals": p.goals,
                "pain_points": p.pain_points,
            }
            for p in personas
        ],
        "survey_findings": survey_findings,
        "interview_messages": interview_messages,
    }

    prompt = f"""
/no_think
You are a research report assistant analyzing SYNTHETIC user research data.

Analyze the following data:
{json.dumps(prompt_data, default=str)}

Return ONLY valid JSON with these keys:
- common_themes: list of strings
- sentiment_summary: object with positive, neutral, negative integer counts
- persona_interests: list of objects containing persona_id, persona_name,
  would_use_product (boolean), reason
- interview_findings: list of strings
- recommendations: list of strings
- conclusion: string

Rules:
- Base findings only on the supplied data.
- Do not claim simulated findings represent real customers.
- Do not invent survey sentiment counts when sentiment labels are unavailable.
- Clearly distinguish observed responses from recommendations.
- Keep recommendations practical and concise.
"""

    try:
        report_data = ollama_service.generate_json(prompt, temperature=0.1, max_tokens=1200)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Could not generate the report. Check that Ollama is running and the model is installed.",
        ) from exc

    return {
        "project_id": project.id,
        "project_name": project.name,
        "product_description": project.product_description,
        "target_market": project.target_market,
        "research_objective": project.research_objective,
        "total_personas": len(personas),
        "total_surveys": len(surveys),
        "total_survey_responses": total_responses,
        "total_interview_sessions": len(interview_sessions),
        "total_interview_messages": len(interview_messages),
        "survey_findings": survey_findings,
        "common_themes": report_data.get("common_themes", []),
        "sentiment_summary": report_data.get("sentiment_summary", {}),
        "persona_interests": report_data.get("persona_interests", []),
        "interview_findings": report_data.get("interview_findings", []),
        "recommendations": report_data.get("recommendations", []),
        "conclusion": report_data.get("conclusion", ""),
    }


@router.get("/{project_id}/pdf")
def download_research_report_pdf(
    project_id: int,
    db: Session = Depends(get_db),
):
    report = generate_research_report(project_id, db)
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        alignment=TA_CENTER,
        textColor=colors.HexColor("#17365D"),
    )

    story = [
        Paragraph("AI Synthetic User Research Report", title_style),
        Spacer(1, 12),
        Paragraph(f"<b>Project:</b> {report['project_name']}", styles["Normal"]),
        Paragraph(f"<b>Product:</b> {report['product_description']}", styles["Normal"]),
        Paragraph(f"<b>Target Market:</b> {report['target_market']}", styles["Normal"]),
        Spacer(1, 12),
        Paragraph("Research Summary", styles["Heading2"]),
    ]

    summary_data = [
        ["Metric", "Count"],
        ["Personas", str(report["total_personas"])],
        ["Surveys", str(report["total_surveys"])],
        ["Survey Responses", str(report["total_survey_responses"])],
        ["Interview Sessions", str(report["total_interview_sessions"])],
        ["Interview Messages", str(report["total_interview_messages"])],
    ]

    table = Table(summary_data, colWidths=[3 * inch, 2 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17365D")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("PADDING", (0, 0), (-1, -1), 7),
    ]))
    story.extend([table, Spacer(1, 12)])

    def add_section(title, content):
        story.append(Paragraph(title, styles["Heading2"]))

        if isinstance(content, list):
            for item in content:
                if title == "Persona Interests" and isinstance(item, dict):
                    name = item.get("persona_name", "Unknown Persona")
                    answer = "Yes" if item.get("would_use_product") else "No"
                    reason = item.get("reason", "Not provided")

                    story.append(Paragraph(
                        f"<b>{name}</b>", styles["Heading3"]
                    ))
                    story.append(Paragraph(
                        f"<b>Would use the product:</b> {answer}",
                        styles["Normal"],
                    ))
                    story.append(Paragraph(
                        f"<b>Reason:</b> {reason}", styles["Normal"]
                    ))
                else:
                    story.append(Paragraph(str(item), styles["Normal"]))
                story.append(Spacer(1, 5))

        elif isinstance(content, dict):
            for key, value in content.items():
                story.append(Paragraph(
                    f"<b>{key}:</b> {value}", styles["Normal"]
                ))

        else:
            story.append(Paragraph(
                str(content or "No data available"), styles["Normal"]
            ))

        story.append(Spacer(1, 10))

    sections = [
        ("Survey Findings", report["survey_findings"]),
        ("Common Themes", report["common_themes"]),
        ("Sentiment Summary", report["sentiment_summary"]),
        ("Persona Interests", report["persona_interests"]),
        ("Interview Findings", report["interview_findings"]),
        ("Recommendations", report["recommendations"]),
        ("Conclusion", report["conclusion"]),
    ]

    for title, content in sections:
        add_section(title, content)

    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "<i>Note: This report contains AI-generated synthetic research "
        "findings. Validate them with real users before making product "
        "decisions.</i>",
        styles["Italic"],
    ))

    doc.build(story)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition":
                f'attachment; filename="research_report_{project_id}.pdf"'
        },
    )
