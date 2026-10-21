"""PDF report rendering with ReportLab (real PDF bytes, paginated, Unicode-capable font)."""
import re
from datetime import datetime
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from app import config
from app.database.models import utcnow

PURPLE = colors.HexColor("#6857e8")
NAVY = colors.HexColor("#171b32")
MUTED = colors.HexColor("#6b7280")
LINE = colors.HexColor("#e3e6ef")

_FONT, _BOLD = "Helvetica", "Helvetica-Bold"


def _register_fonts() -> None:
    global _FONT, _BOLD
    regular, bold = config.FONT_DIR / "DejaVuSans.ttf", config.FONT_DIR / "DejaVuSans-Bold.ttf"
    if regular.exists() and bold.exists():
        if "SynSans" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("SynSans", str(regular)))
            pdfmetrics.registerFont(TTFont("SynSans-Bold", str(bold)))
            pdfmetrics.registerFontFamily("SynSans", normal="SynSans", bold="SynSans-Bold",
                                          italic="SynSans", boldItalic="SynSans-Bold")
        _FONT, _BOLD = "SynSans", "SynSans-Bold"


def _styles() -> dict:
    _register_fonts()
    base = dict(fontName=_FONT, fontSize=9.5, leading=14, textColor=colors.HexColor("#1f2937"), alignment=TA_LEFT)
    return {
        "title": ParagraphStyle("title", fontName=_BOLD, fontSize=20, leading=25, textColor=NAVY, spaceAfter=4),
        "subtitle": ParagraphStyle("subtitle", **{**base, "fontSize": 10, "textColor": MUTED}),
        "h1": ParagraphStyle("h1", fontName=_BOLD, fontSize=13, leading=17, textColor=PURPLE, spaceBefore=14, spaceAfter=6),
        "h2": ParagraphStyle("h2", fontName=_BOLD, fontSize=11, leading=15, textColor=NAVY, spaceBefore=10, spaceAfter=4),
        "body": ParagraphStyle("body", **base),
        "answer": ParagraphStyle("answer", **{**base, "leftIndent": 10}),
        "who": ParagraphStyle("who", **{**base, "fontName": _BOLD, "leftIndent": 10, "textColor": NAVY, "spaceBefore": 5}),
        "small": ParagraphStyle("small", **{**base, "fontSize": 8, "leading": 11, "textColor": MUTED}),
        "notice": ParagraphStyle("notice", **{**base, "fontSize": 8.5, "textColor": colors.HexColor("#7c2d12"),
                                              "backColor": colors.HexColor("#fff7ed"), "borderPadding": 6,
                                              "borderColor": colors.HexColor("#fdba74"), "borderWidth": 0.5}),
    }


def esc(value) -> str:
    """XML-escape arbitrary text for Paragraph, preserving line breaks."""
    if value is None or value == "":
        return "—"
    return escape(str(value)).replace("\r\n", "\n").replace("\n", "<br/>")


def fmt_dt(dt) -> str:
    return dt.strftime("%d %b %Y, %H:%M UTC") if isinstance(dt, datetime) else "—"


def safe_filename(title: str, prefix: str, ident: int) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", title or "").strip("-").lower()[:50] or "report"
    return f"synuser-{prefix}-{ident}-{slug}.pdf"


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont(_FONT, 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 10 * mm, "SynUser · AI-generated synthetic research — not real customer data")
    canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
    canvas.setStrokeColor(LINE)
    canvas.line(18 * mm, 14 * mm, A4[0] - 18 * mm, 14 * mm)
    canvas.restoreState()


def _kv_table(rows: list[tuple[str, object]], st: dict) -> Table:
    data = [[Paragraph(f"<b>{esc(k)}</b>", st["small"]), Paragraph(esc(v), st["body"])] for k, v in rows]
    t = Table(data, colWidths=[38 * mm, None])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
                           ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return t


def _header(st: dict, report_title: str, project_name: str, subtitle: str) -> list:
    return [Paragraph("SynUser <font color='#6857e8'>AI Research Studio</font>", st["small"]),
            Spacer(1, 4), Paragraph(esc(report_title), st["title"]),
            Paragraph(f"Project: {esc(project_name)} &nbsp;·&nbsp; {esc(subtitle)}", st["subtitle"]),
            Spacer(1, 4), HRFlowable(width="100%", thickness=1, color=PURPLE), Spacer(1, 6)]


def _build(story: list) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=20 * mm, title="SynUser report", author="SynUser")
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()


def survey_pdf(results: dict, ai_summary: dict | None = None, summary_note: str | None = None) -> bytes:
    st = _styles()
    proj = results["project"]
    story = _header(st, results["survey_title"], proj["name"], f"Generated {fmt_dt(utcnow())}")
    story.append(Paragraph(esc(results["disclaimer"]), st["notice"]))
    story.append(Paragraph("Project details", st["h1"]))
    story.append(_kv_table([("Project", proj["name"]), ("Description", proj.get("description")),
                            ("Target audience", proj.get("target_market")),
                            ("Project objective", proj.get("research_objective"))], st))
    story.append(Paragraph("Survey details", st["h1"]))
    story.append(_kv_table([("Survey title", results["survey_title"]),
                            ("Research objective", results.get("research_objective")),
                            ("Research topic", results.get("research_topic")),
                            ("Status", results["status"]), ("Created", fmt_dt(results.get("created_at"))),
                            ("Completed", fmt_dt(results.get("completed_at"))),
                            ("Questions / personas", f"{results['total_questions']} / {results['total_personas']}"),
                            ("Responses saved", f"{results['total_responses']} of {results['expected_responses']}")], st))
    story.append(Paragraph("Participating synthetic personas", st["h1"]))
    for p in results["personas"]:
        bits = [x for x in (p.get("occupation"), f"age {p['age']}" if p.get("age") else None, p.get("location")) if x]
        block = [Paragraph(f"<b>{esc(p['name'])}</b> — {esc(', '.join(bits) or 'no details')}", st["body"])]
        for label, key in (("Goals", "goals"), ("Pain points", "pain_points"), ("Preferences", "preferences")):
            if p.get(key):
                block.append(Paragraph(f"<b>{label}:</b> {esc(p[key])}", st["answer"]))
        block.append(Spacer(1, 5))
        story.append(KeepTogether(block))
    if ai_summary:
        story.append(Paragraph("AI-generated thematic summary", st["h1"]))
        story.append(Paragraph("Interpretation of synthetic responses generated by a language model.", st["small"]))
        story.append(Paragraph(esc(ai_summary["summary"]), st["body"]))
        for t in ai_summary.get("themes", []):
            story.append(Paragraph(f"• {esc(t)}", st["answer"]))
    elif summary_note:
        story.append(Paragraph(esc(summary_note), st["small"]))
    story.append(Paragraph("Survey results", st["h1"]))
    for n, r in enumerate(results["results"], start=1):
        story.append(Paragraph(f"Question {n}: {esc(r['question_text'])}", st["h2"]))
        if not r["answers"]:
            story.append(Paragraph("No responses saved for this question.", st["answer"]))
        for a in r["answers"]:
            who = f"{esc(a['persona_name'])}" + (f", {esc(a['persona_occupation'])}" if a.get("persona_occupation") else "")
            story.append(Paragraph(who, st["who"]))
            story.append(Paragraph(esc(a["answer"]), st["answer"]))
    if results["failed_items"]:
        story.append(Paragraph("Responses not generated", st["h1"]))
        for f in results["failed_items"]:
            story.append(Paragraph(f"• {esc(f['persona_name'])} — {esc(f['question_text'])}", st["answer"]))
    return _build(story)


def interview_pdf(d: dict, ai_summary: dict | None = None, summary_note: str | None = None) -> bytes:
    st = _styles()
    proj, p = d["project"], d["persona"]
    story = _header(st, d["title"], proj["name"], f"Interview report · generated {fmt_dt(utcnow())}")
    story.append(Paragraph(esc(d["disclaimer"]), st["notice"]))
    story.append(Paragraph("Project details", st["h1"]))
    story.append(_kv_table([("Project", proj["name"]), ("Description", proj.get("description")),
                            ("Target audience", proj.get("target_market"))], st))
    story.append(Paragraph("Interview details", st["h1"]))
    story.append(_kv_table([("Title", d["title"]), ("Research topic", d.get("research_topic")),
                            ("Objective", d.get("research_objective")), ("Interview guide", d.get("interview_guide")),
                            ("Status", d["status"]), ("Started", fmt_dt(d.get("created_at"))),
                            ("Last activity", fmt_dt(d.get("last_activity_at"))),
                            ("Messages", d["message_count"])], st))
    story.append(Paragraph("Persona profile (synthetic)", st["h1"]))
    income = f"{float(p.income):,.0f}" if getattr(p, "income", None) is not None else None
    story.append(_kv_table([("Name", p.name), ("Age", p.age), ("Occupation", p.occupation), ("Income / month", income),
                            ("Location", p.location), ("Experience", p.experience_level),
                            ("Personality", p.personality), ("Goals", p.goals), ("Preferences", p.preferences),
                            ("Pain points", p.pain_points)], st))
    if ai_summary:
        story.append(Paragraph("AI-generated summary of the simulated responses", st["h1"]))
        story.append(Paragraph(esc(ai_summary["summary"]), st["body"]))
        for title, key in (("Main needs", "needs"), ("Preferences", "preferences"),
                           ("Pain points", "pain_points"), ("Recommendations", "recommendations")):
            if ai_summary.get(key):
                story.append(Paragraph(title, st["h2"]))
                for item in ai_summary[key]:
                    story.append(Paragraph(f"• {esc(item)}", st["answer"]))
    elif summary_note:
        story.append(Paragraph(esc(summary_note), st["small"]))
    story.append(Paragraph("Transcript", st["h1"]))
    if not d["messages"]:
        story.append(Paragraph("No messages were exchanged.", st["body"]))
    for m in d["messages"]:
        label = "Researcher" if m.role == "researcher" else esc(p.name)
        story.append(Paragraph(f"{label} <font size=7 color='#9ca3af'>#{m.sequence_number or ''} · {fmt_dt(m.created_at)}</font>", st["who"]))
        story.append(Paragraph(esc(m.message_text), st["answer"]))
    return _build(story)
