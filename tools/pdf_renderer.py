"""Synthetic borehole log PDF renderer.

Adapted from generate_pdf.py: same depth-scaled vertical layout, same
column geometry, but the data source is the in-memory synthetic dataset
(SyntheticSample list + borehole header dict) rather than Supabase.

Firm style controls column headers and whether the description column uses
the firm's abbreviations.
"""

from __future__ import annotations

import io
from typing import Any, Dict, List
from xml.sax.saxutils import escape as _xml_escape

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

from tools.firm_styles import FirmStyle
from tools.soil_corpus import SyntheticSample


# ── Layout constants (mirrors generate_pdf.py) ──

PAGE_W, PAGE_H = letter
MARGIN = 0.5 * inch
USABLE_W = PAGE_W - 2 * MARGIN
SCALE_PT_PER_FT = 0.45 * inch

COL_WIDTHS = {
    "depth":    0.50 * inch,
    "sample":   0.55 * inch,
    "desc":     2.75 * inch,
    "blows":    0.75 * inch,
    "n":        0.55 * inch,   # widened — fits "N-Value" header without overlap
    "rec":      0.70 * inch,   # widened — fits "Recovery (in)" header without overlap
    "comments": 1.70 * inch,
}

HEADER_BG = colors.HexColor("#2C3E50")
SAMPLE_HIGHLIGHT = colors.HexColor("#EAEFF3")
BORDER = colors.grey
BORDER_HEAVY = colors.black

FS_TITLE = 13
FS_HDR_LABEL = 8
FS_HDR_VALUE = 9
FS_BODY = 8
FS_DEPTH = 7.5

COL_HDR_HEIGHT = 16
FULL_HEADER_H = 1.55 * inch
FULL_HEADER_GAP = 0.12 * inch


DESC_STYLE = ParagraphStyle(
    "desc", fontName="Helvetica", fontSize=FS_BODY, leading=10, alignment=TA_LEFT
)
COMMENT_STYLE = ParagraphStyle(
    "cmt", fontName="Helvetica", fontSize=FS_BODY, leading=9.5, alignment=TA_LEFT
)


def _fmt_num(v):
    if v is None:
        return ""
    try:
        f = float(v)
        return str(int(f)) if f == int(f) else f"{f}"
    except (ValueError, TypeError):
        return str(v)


def _apply_abbreviations(text: str, abbr: Dict[str, str]) -> str:
    """Reverse the abbreviation map and rewrite description.

    For each abbreviation alias (e.g. "Sa" -> "sand"), substitute the full
    soil term in the description with the alias. This is what makes Firm-B's
    PDF read "SaCl, brown, moist" instead of "Sandy clay, brown, moist".
    """
    if not abbr:
        return text
    # Sort by canonical-term length DESC to substitute longer matches first
    # (e.g. "sandy clay" before "clay").
    items = sorted(abbr.items(), key=lambda kv: -len(kv[1]))
    out = text
    for alias, canonical in items:
        # Replace at word boundary, case-insensitive, but preserve sentence start
        # by uppercase first letter.
        import re
        pattern = re.compile(r"\b" + re.escape(canonical) + r"\b", re.IGNORECASE)
        out = pattern.sub(alias, out)
    return out


# ── Borehole header ──

def _draw_header(c: canvas.Canvas, borehole: Dict[str, Any], firm: FirmStyle) -> float:
    top = PAGE_H - MARGIN
    bottom = top - FULL_HEADER_H

    c.setStrokeColor(BORDER_HEAVY)
    c.setLineWidth(1.0)
    c.rect(MARGIN, bottom, USABLE_W, FULL_HEADER_H, stroke=1, fill=0)

    # Title bar
    title_h = 0.28 * inch
    c.setFillColor(HEADER_BG)
    c.rect(MARGIN, top - title_h, USABLE_W, title_h, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", FS_TITLE)
    c.drawString(
        MARGIN + 8, top - title_h + 8,
        f"BORING LOG — {borehole.get('borehole_no','')}   ({firm.firm_name})",
    )
    c.setFillColor(colors.black)

    left_fields = [
        ("Project No",  borehole.get("project_no", "")),
        ("Location",    borehole.get("location", "")),
        ("Lat / Lon",   _coords(borehole)),
        ("Datum",       borehole.get("datum") or ""),
    ]
    right_fields = [
        ("Borehole ID",       borehole.get("borehole_no", "")),
        ("Total Depth (ft)",  _fmt_num(borehole.get("total_depth_ft"))),
        ("Hammer",            borehole.get("hammer_type") or ""),
        ("Groundwater (ft)",  _gw_str(borehole.get("groundwater"))),
    ]

    field_top = top - title_h - 0.18 * inch
    line_h = 0.24 * inch
    label_w = 1.05 * inch
    half_w = USABLE_W / 2

    def _draw_col(fields, col_x):
        for i, (label, value) in enumerate(fields):
            y = field_top - i * line_h
            c.setFont("Helvetica-Bold", FS_HDR_LABEL)
            c.drawString(col_x, y, f"{label}:")
            c.setFont("Helvetica", FS_HDR_VALUE)
            c.drawString(col_x + label_w, y, str(value or ""))

    _draw_col(left_fields, MARGIN + 8)
    _draw_col(right_fields, MARGIN + half_w + 4)

    c.setStrokeColor(BORDER)
    c.setLineWidth(0.4)
    c.line(MARGIN + half_w, top - title_h - 4, MARGIN + half_w, bottom + 4)
    return bottom - FULL_HEADER_GAP


def _coords(borehole: Dict[str, Any]) -> str:
    lat, lon = borehole.get("latitude"), borehole.get("longitude")
    if lat is None or lon is None:
        return ""
    return f"{lat:.4f}, {lon:.4f}"


def _gw_str(gw):
    if not gw:
        return ""
    enc = gw.get("encountered_ft")
    stab = gw.get("stabilized_ft")
    if enc is None and stab is None:
        return "dry" if gw.get("dry") else ""
    return f"enc {enc} / stab {stab}"


# ── Column headers ──

def _build_col_x(order):
    out = {}
    x = MARGIN
    for name in order:
        w = COL_WIDTHS[name]
        out[name] = (x, w)
        x += w
    return out


def _draw_column_headers(c: canvas.Canvas, y_top: float, firm: FirmStyle) -> float:
    order = firm.column_order
    cols = _build_col_x(order)
    bottom = y_top - COL_HDR_HEIGHT
    c.setFillColor(HEADER_BG)
    c.rect(MARGIN, bottom, USABLE_W, COL_HDR_HEIGHT, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", FS_BODY)
    for name in order:
        x, w = cols[name]
        label = firm.column_labels[name]
        # Auto-shrink the font if a firm style happens to ship a label wider than
        # its column. Defensive — current configs fit at FS_BODY but future
        # firms may add verbose headers we'd rather scale than truncate.
        font_size = FS_BODY
        tw = c.stringWidth(label, "Helvetica-Bold", font_size)
        while tw > w - 2 and font_size > 5:
            font_size -= 0.5
            c.setFont("Helvetica-Bold", font_size)
            tw = c.stringWidth(label, "Helvetica-Bold", font_size)
        c.drawString(x + (w - tw) / 2, bottom + 5, label)
        c.setFont("Helvetica-Bold", FS_BODY)  # restore for subsequent labels
    c.setStrokeColor(colors.white)
    c.setLineWidth(0.4)
    for name in order[1:]:
        x, _ = cols[name]
        c.line(x, bottom, x, y_top)
    c.setFillColor(colors.black)
    return bottom


def _draw_body_frame(c, body_top_y, body_bot_y, page_top_ft, page_bot_ft, cols):
    body_h = body_top_y - body_bot_y
    c.setStrokeColor(BORDER)
    c.setLineWidth(0.4)
    c.rect(MARGIN, body_bot_y, USABLE_W, body_h, stroke=1, fill=0)
    for name in list(cols)[1:]:
        x, _ = cols[name]
        c.line(x, body_top_y, x, body_bot_y)

    # 1-ft depth ticks
    dx, dw = cols["depth"]
    c.setFont("Helvetica", FS_DEPTH)
    ft = int(page_top_ft) if page_top_ft == int(page_top_ft) else int(page_top_ft) + 1
    while ft <= page_bot_ft + 1e-6:
        y = body_top_y - (ft - page_top_ft) * SCALE_PT_PER_FT
        if y < body_bot_y:
            break
        c.line(dx, y, dx + dw * 0.30, y)
        c.drawString(dx + dw * 0.36, y - FS_DEPTH / 2 + 1, str(ft))
        ft += 1


# ── Sample row ──

def _draw_sample(c, sample: SyntheticSample, firm: FirmStyle,
                 page_top_ft, body_top_y, cols):
    top_ft = sample.depth_ft
    length_ft = sum(sample.pen_depths) / 12.0
    bot_ft = top_ft + length_ft

    y_top = body_top_y - (top_ft - page_top_ft) * SCALE_PT_PER_FT
    y_bot = body_top_y - (bot_ft - page_top_ft) * SCALE_PT_PER_FT
    box_h = y_top - y_bot

    # Sample column highlight
    sx, sw = cols["sample"]
    c.setFillColor(SAMPLE_HIGHLIGHT)
    c.rect(sx, y_bot, sw, box_h, stroke=0, fill=1)

    c.setStrokeColor(BORDER)
    c.setLineWidth(0.5)
    c.line(MARGIN, y_top, MARGIN + USABLE_W, y_top)
    c.line(MARGIN, y_bot, MARGIN + USABLE_W, y_bot)

    # Sample id
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", FS_BODY + 1)
    label = f"SS-{sample.sample_no}"
    tw = c.stringWidth(label, "Helvetica-Bold", FS_BODY + 1)
    c.drawString(sx + (sw - tw) / 2, y_top - 11, label)

    # Description (with firm-specific abbreviations applied)
    dx, dw = cols["desc"]
    desc_text = _apply_abbreviations(sample.description, firm.abbreviations)
    para = Paragraph(_xml_escape(desc_text), DESC_STYLE)
    para.wrapOn(c, dw - 8, box_h - 4)
    para.drawOn(c, dx + 4, y_top - para.height - 2)

    # N-value
    nx, nw = cols["n"]
    if sample.n_value is not None:
        c.setFont("Helvetica-Bold", FS_BODY)
        txt = str(sample.n_value)
        tw = c.stringWidth(txt, "Helvetica-Bold", FS_BODY)
        c.drawString(nx + (nw - tw) / 2, y_bot + (box_h - FS_BODY) / 2 + 1, txt)

    # Recovery
    rx, rw = cols["rec"]
    if sample.recovery_inches is not None:
        c.setFont("Helvetica", FS_BODY)
        txt = _fmt_num(sample.recovery_inches)
        tw = c.stringWidth(txt, "Helvetica", FS_BODY)
        c.drawString(rx + (rw - tw) / 2, y_bot + (box_h - FS_BODY) / 2 + 1, txt)

    # Comments: surface lab data here so PDF carries every fact in ground truth
    cx, cw = cols["comments"]
    cmt_parts = []
    if sample.lab_tests:
        lt = sample.lab_tests
        if "moisture_content_pct" in lt:
            cmt_parts.append(f"w = {lt['moisture_content_pct']}%")
        if "atterberg" in lt:
            a = lt["atterberg"]
            cmt_parts.append(f"LL/PL/PI = {a['ll']}/{a['pl']}/{a['pi']}")
        if "grain_size_pct" in lt:
            gs = lt["grain_size_pct"]
            cmt_parts.append(f"%G/S/F = {gs['gravel']}/{gs['sand']}/{gs['fines']}")
    if sample.refusal:
        cmt_parts.append(f"REFUSAL ({sample.n_value_log})")
    if cmt_parts:
        para = Paragraph("<br/>".join(cmt_parts), COMMENT_STYLE)
        para.wrapOn(c, cw - 8, box_h - 4)
        para.drawOn(c, cx + 4, y_top - para.height - 2)

    # Blow-count boxes
    bx, bw = cols["blows"]
    cur_ft = top_ft
    for i, bc in enumerate(sample.blow_counts):
        pd = sample.pen_depths[i]
        inc_top = cur_ft
        inc_bot = cur_ft + pd / 12.0
        cur_ft = inc_bot
        iy_top = body_top_y - (inc_top - page_top_ft) * SCALE_PT_PER_FT
        iy_bot = body_top_y - (inc_bot - page_top_ft) * SCALE_PT_PER_FT
        ih = iy_top - iy_bot
        c.rect(bx, iy_bot, bw, ih, stroke=1, fill=0)
        txt = str(bc) if pd == 6 else f"{bc}/{_fmt_num(pd)}\""
        c.setFont("Helvetica", FS_BODY)
        tw = c.stringWidth(txt, "Helvetica", FS_BODY)
        c.drawString(bx + (bw - tw) / 2, iy_bot + (ih - FS_BODY) / 2 + 1, txt)


# ── Public entry point ──

def render_pdf(borehole: Dict[str, Any], samples: List[SyntheticSample],
               firm: FirmStyle) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setTitle(f"Synthetic Boring Log {borehole.get('borehole_no','')}")

    header_bottom = _draw_header(c, borehole, firm)
    cols = _build_col_x(firm.column_order)
    col_hdr_bottom = _draw_column_headers(c, header_bottom, firm)

    body_top_y = col_hdr_bottom

    # Total depth from samples (uses sum(pen_depths)/12 per sample, plus depth_ft top).
    total_depth = 0.0
    for s in samples:
        bot = s.depth_ft + sum(s.pen_depths) / 12.0
        if bot > total_depth:
            total_depth = bot

    # For Chunk 3 simplicity: single page. If we ever need multipage, copy
    # generate_pdf.py's paging loop.
    body_bot_y = body_top_y - total_depth * SCALE_PT_PER_FT
    # Clamp body to remain on-page; if it would overflow, scale down.
    if body_bot_y < MARGIN:
        scale = (body_top_y - MARGIN) / (total_depth * SCALE_PT_PER_FT)
        # Re-render with adjusted scale by stretching cols (simplest: just clamp).
        body_bot_y = MARGIN

    _draw_body_frame(c, body_top_y, body_bot_y, 0.0, total_depth, cols)
    for s in samples:
        _draw_sample(c, s, firm, 0.0, body_top_y, cols)

    c.showPage()
    c.save()
    return buf.getvalue()
