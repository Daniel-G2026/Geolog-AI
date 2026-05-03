"""Generate the GeoLog AI pilot-readiness checklist PDF."""
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
)
from reportlab.lib.enums import TA_LEFT

OUTPUT = "GeoLog_AI_Pilot_Readiness_Checklist.pdf"

# ── Colors (match the field-cockpit palette) ─────────────────────────────────
INK         = colors.HexColor("#161c20")
INK_2       = colors.HexColor("#2b3640")
MUTED       = colors.HexColor("#5a6770")
BLUEPRINT   = colors.HexColor("#14467c")
RECORD      = colors.HexColor("#e2511f")
GREEN       = colors.HexColor("#1f7a3d")
GREEN_BG    = colors.HexColor("#d7ebde")
AMBER       = colors.HexColor("#c98a00")
AMBER_BG    = colors.HexColor("#fff3d2")
RED         = colors.HexColor("#b3261e")
RED_BG      = colors.HexColor("#f9dedc")
RULE        = colors.HexColor("#b8bfb8")
PAPER       = colors.HexColor("#f7f8f5")

# ── Styles ───────────────────────────────────────────────────────────────────
styles = getSampleStyleSheet()
title_style = ParagraphStyle(
    "title", parent=styles["Title"],
    fontName="Helvetica-Bold", fontSize=22, leading=26,
    textColor=INK, spaceAfter=4,
)
subtitle_style = ParagraphStyle(
    "subtitle", parent=styles["Normal"],
    fontName="Helvetica", fontSize=11, leading=14,
    textColor=MUTED, spaceAfter=18,
)
verdict_style = ParagraphStyle(
    "verdict", parent=styles["Normal"],
    fontName="Helvetica-Bold", fontSize=14, leading=18,
    textColor=colors.white, alignment=TA_LEFT,
    leftIndent=10, rightIndent=10,
)
h2 = ParagraphStyle(
    "h2", parent=styles["Heading2"],
    fontName="Helvetica-Bold", fontSize=14, leading=18,
    textColor=BLUEPRINT, spaceBefore=14, spaceAfter=6,
)
h3 = ParagraphStyle(
    "h3", parent=styles["Heading3"],
    fontName="Helvetica-Bold", fontSize=11, leading=14,
    textColor=INK_2, spaceBefore=10, spaceAfter=4,
)
body = ParagraphStyle(
    "body", parent=styles["Normal"],
    fontName="Helvetica", fontSize=10, leading=14,
    textColor=INK, spaceAfter=6,
)
small = ParagraphStyle(
    "small", parent=styles["Normal"],
    fontName="Helvetica", fontSize=9, leading=12,
    textColor=MUTED,
)
mono_label = ParagraphStyle(
    "mono", parent=styles["Normal"],
    fontName="Courier-Bold", fontSize=9, leading=12, textColor=INK,
)

def status_badge(text, color, bg):
    return Paragraph(
        f'<font color="{color.hexval()}"><b>{text}</b></font>', body
    )

def page_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(0.75 * inch, 0.5 * inch, "GeoLog AI · Pilot Readiness Checklist")
    canvas.drawRightString(LETTER[0] - 0.75 * inch, 0.5 * inch, f"Page {doc.page}")
    canvas.restoreState()

# ── Document ─────────────────────────────────────────────────────────────────
doc = SimpleDocTemplate(
    OUTPUT, pagesize=LETTER,
    leftMargin=0.75*inch, rightMargin=0.75*inch,
    topMargin=0.7*inch, bottomMargin=0.7*inch,
    title="GeoLog AI Pilot Readiness Checklist",
    author="GeoLog AI",
)
story = []

# Title block
story.append(Paragraph("GeoLog AI", title_style))
story.append(Paragraph("Pilot Readiness Checklist &nbsp;·&nbsp; 2026-05-03", subtitle_style))

# Verdict banner
verdict_tbl = Table(
    [[Paragraph("Current status:&nbsp; <b>READY FOR CONTROLLED FIELD TEST</b><br/>"
                "<font size=10>Not yet ready for unobserved multi-tech pilot.</font>", verdict_style)]],
    colWidths=[7.0*inch],
)
verdict_tbl.setStyle(TableStyle([
    ("BACKGROUND", (0,0), (-1,-1), AMBER),
    ("TEXTCOLOR",  (0,0), (-1,-1), colors.white),
    ("LEFTPADDING",(0,0), (-1,-1), 12),
    ("RIGHTPADDING",(0,0), (-1,-1), 12),
    ("TOPPADDING", (0,0), (-1,-1), 12),
    ("BOTTOMPADDING",(0,0), (-1,-1), 12),
    ("ROUNDEDCORNERS", [6,6,6,6]),
]))
story.append(verdict_tbl)
story.append(Spacer(1, 18))

# Why not pilot — section
story.append(Paragraph("Why not pilot yet", h2))
story.append(Paragraph(
    "The code is in good shape — state, recording, sync, and interruption handling have all "
    "been hardened through repeated audits. What's missing is the operational layer around it: "
    "real-device QA, network resilience, the export deliverable, and a way to debug failures "
    "200&nbsp;km from a desk. The items below are not code review findings; they are field-readiness "
    "gaps that code review cannot validate.",
    body
))
story.append(Spacer(1, 6))

# Six gap categories
gaps = [
    ("1. No real-device testing yet",
     "Every interruption fix (visibilitychange, pagehide, mediaRecorder.onerror, MIME fallback) "
     "was verified by reasoning about specs. Real iOS Safari and real Android Chrome on actual "
     "phones during real phone calls are needed before unobserved use.",
     [
        "iOS Safari 14 / 15 / 16 differences in MediaRecorder codec output",
        "Android Chrome behaviour when an incoming call notification appears (often does NOT fire visibilitychange)",
        "iOS Low Power Mode throttling background fetch on the upload step",
        "Bluetooth headset switching mid-recording",
        "Cellular handoff (LTE→5G→LTE) during a 30s upload",
     ]),
    ("2. No backend load or failure-mode testing",
     "Whisper latency, concurrent uploads, and Supabase rate limits have not been exercised under "
     "realistic conditions.",
     [
        "Whisper takes 90s instead of 10s — frontend has no upload timeout, will wait forever",
        "Two techs uploading drafts on the same project simultaneously — never tested",
        "Supabase 5xx / rate-limit responses surface as generic 'Pipeline error'; no retry-vs-fail distinction",
     ]),
    ("3. Open data-integrity gap (low frequency, real)",
     "Backend confirm_sample (app.py:316–372) does a non-atomic check-then-insert. Two devices "
     "saving simultaneously at the same depth can both pass the pre-check before either inserts. "
     "Supabase rejects the second on the unique constraint (good), but the frontend will surface "
     "a confusing 'duplicate' error after the user thought their save was in flight.",
     [
        "Add a UNIQUE constraint test",
        "Surface a clearer 'this exact sample already exists' message distinct from generic save errors",
     ]),
    ("4. No PDF export",
     "The product promise is 'Generate Borehole Log PDF' once samples exist. The button is "
     "wired-but-disabled. Pilot users will lose trust if a full day of logging produces no "
     "exportable artifact.",
     []),
    ("5. No offline / poor-network mode",
     "Field sites have patchy LTE. The retry button helps for one failed upload, but if the tech "
     "logs five samples in a no-signal area, they will lose all five. The whole point of the app "
     "is that it works at the drill rig, not at the office.",
     [
        "Offline draft queue (record + queue + flush when network returns)",
        "Local persistence of recordings until confirmed-saved server-side",
     ]),
    ("6. No observability",
     "If a tech reports 'the app didn't save my sample,' there is no way to investigate. No "
     "client-side error logging, no server-side request log surfacing, no support contact path. "
     "Pilot without this is operating blind.",
     [
        "Client error logging (Sentry or equivalent)",
        "Surface request-id / sample-id in success and error toasts so a tech can quote them",
     ]),
]

for h, p, bullets in gaps:
    story.append(Paragraph(h, h3))
    story.append(Paragraph(p, body))
    if bullets:
        for b in bullets:
            story.append(Paragraph(f"&bull;&nbsp;&nbsp;{b}", body))
    story.append(Spacer(1, 4))

story.append(PageBreak())

# Pilot-ready checklist table
story.append(Paragraph("Pilot-ready checklist", h2))
story.append(Paragraph(
    "Ordered by importance. Items at the top must land before pilot; items at the bottom are "
    "already confirmed durable from code review.",
    small
))
story.append(Spacer(1, 8))

# header row + items
def cell(text, style=body):
    return Paragraph(text, style)

def status_cell(done):
    if done:
        return Paragraph(f'<font color="{GREEN.hexval()}"><b>&#10003; DONE</b></font>', body)
    return Paragraph(f'<font color="{RED.hexval()}"><b>&#10007; OPEN</b></font>', body)

rows = [
    [Paragraph("<b>Status</b>", body), Paragraph("<b>Item</b>", body)],
    [status_cell(False),
     cell("Real-device QA: iOS Safari + Android Chrome on actual phones, real phone calls, real cellular")],
    [status_cell(False),
     cell("Add fetch timeouts (60s for draft, 30s for everything else)")],
    [status_cell(False),
     cell("Offline draft queue (record + queue + flush when network returns)")],
    [status_cell(False),
     cell("PDF export endpoint + wire the disabled button")],
    [status_cell(False),
     cell("Atomic confirm (Supabase RPC with constraint, or rely on the unique index and surface duplicate cleanly)")],
    [status_cell(False),
     cell("Client error logging (Sentry or equivalent)")],
    [status_cell(False),
     cell("Battery test: a tech doing 30 samples on a single charge with screen-on")],
    [status_cell(True),
     cell("Code-level durability (state, recording, sync, interruption handling)")],
    [status_cell(True),
     cell("Backend contract integrity")],
    [status_cell(True),
     cell("Mobile UI affordances (touch targets, sunlight palette, one-handed cockpit)")],
]

tbl = Table(rows, colWidths=[1.0*inch, 6.0*inch], repeatRows=1)
tbl.setStyle(TableStyle([
    ("BACKGROUND", (0,0), (-1,0), INK),
    ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
    ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
    ("FONTSIZE",   (0,0), (-1,0), 10),
    ("BOTTOMPADDING",(0,0), (-1,0), 8),
    ("TOPPADDING", (0,0), (-1,0), 8),
    ("BACKGROUND", (0,1), (-1,-1), PAPER),
    ("ROWBACKGROUNDS", (0,1), (-1,-1), [PAPER, colors.white]),
    ("LINEBELOW",  (0,0), (-1,-1), 0.5, RULE),
    ("VALIGN",     (0,0), (-1,-1), "TOP"),
    ("LEFTPADDING",(0,0), (-1,-1), 8),
    ("RIGHTPADDING",(0,0), (-1,-1), 8),
    ("TOPPADDING", (0,1), (-1,-1), 8),
    ("BOTTOMPADDING",(0,1), (-1,-1), 8),
    ("BOX",        (0,0), (-1,-1), 0.75, RULE),
]))
story.append(tbl)
story.append(Spacer(1, 18))

# Recommendation block
story.append(Paragraph("Recommendation", h2))
rec_tbl = Table([[Paragraph(
    "Run the controlled field test first &mdash; one tech, you observing, ideally somewhere with "
    "bad signal on purpose. The findings from that session will tell you which of the seven open "
    "items above need to land before pilot.<br/><br/>"
    "<b>Honest summary:</b> the code is in good shape. What is missing is the operational layer "
    "around it &mdash; testing on hardware, network resilience, the export deliverable, and a way "
    "to debug failures when they happen 200&nbsp;km from a desk.",
    body
)]], colWidths=[7.0*inch])
rec_tbl.setStyle(TableStyle([
    ("BACKGROUND", (0,0), (-1,-1), GREEN_BG),
    ("LINEBEFORE", (0,0), (0,-1), 4, GREEN),
    ("LEFTPADDING",(0,0), (-1,-1), 12),
    ("RIGHTPADDING",(0,0), (-1,-1), 12),
    ("TOPPADDING", (0,0), (-1,-1), 12),
    ("BOTTOMPADDING",(0,0), (-1,-1), 12),
]))
story.append(rec_tbl)

doc.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
print(f"Wrote {OUTPUT}")
