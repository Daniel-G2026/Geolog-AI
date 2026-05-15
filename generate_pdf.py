"""Standalone boring log PDF generator.

Renders a borehole as a depth-scaled vertical log: 1 ft on the page
corresponds to a fixed number of points, samples occupy their actual depth
intervals, and SPT blow counts stack as 6-inch increment boxes aligned to
the depth scale. Paginates automatically when borehole depth overruns one
page; depth scale stays consistent across pages.
"""

import io
import json
from xml.sax.saxutils import escape as _xml_escape

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

from app import supabase_client


# ── Layout constants (tweak here) ──

PAGE_W, PAGE_H = letter
MARGIN = 0.5 * inch
USABLE_W = PAGE_W - 2 * MARGIN  # 7.5"

# Vertical scale: 1 ft of borehole = this many points on the page.
# 0.5" per ft → ~16 ft on page 1 (after full header), ~18 ft per subsequent page.
SCALE_PT_PER_FT = 0.45 * inch

# Column widths must sum to USABLE_W (= 7.5")
COL_WIDTHS = {
    "depth":    0.55 * inch,  # depth scale gutter
    "sample":   0.55 * inch,  # sample ID
    "desc":     3.05 * inch,  # description (widest readable column)
    "blows":    0.70 * inch,  # stacked blow boxes
    "n":        0.35 * inch,  # N-value
    "rec":      0.50 * inch,  # recovery (in)
    "comments": 1.80 * inch,  # comments / flags
}
COL_ORDER = ["depth", "sample", "desc", "blows", "n", "rec", "comments"]
COL_LABELS = {
    "depth": "Depth (ft)",
    "sample": "Sample",
    "desc": "Description",
    "blows": "Blows",
    "n": "N",
    "rec": "Rec (in)",
    "comments": "Comments / Flags",
}

# Colors
HEADER_BG = colors.HexColor("#2C3E50")
SAMPLE_HIGHLIGHT = colors.HexColor("#EAEFF3")
ROW_ALT_BG = colors.HexColor("#F5F5F5")
BORDER = colors.grey
BORDER_HEAVY = colors.black
FLAG_HEX = "#B7472A"

# Font sizes
FS_TITLE = 13
FS_HDR_LABEL = 8
FS_HDR_VALUE = 9
FS_BODY = 8
FS_DEPTH = 7.5
FS_COMMENT = 7.5

COL_HDR_HEIGHT = 16

# Header block heights
FULL_HEADER_H = 1.55 * inch
FULL_HEADER_GAP = 0.12 * inch
COMPACT_HEADER_H = 0.30 * inch
COMPACT_HEADER_GAP = 0.08 * inch


# ── Paragraph styles ──

DESC_STYLE = ParagraphStyle(
    "desc", fontName="Helvetica", fontSize=FS_BODY, leading=10, alignment=TA_LEFT
)
COMMENT_STYLE = ParagraphStyle(
    "cmt", fontName="Helvetica", fontSize=FS_COMMENT, leading=9.5, alignment=TA_LEFT
)


# ── JSON / formatting helpers ──

def _loads(value, default):
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _fmt_num(v):
    if v is None:
        return ""
    try:
        f = float(v)
        return str(int(f)) if f == int(f) else f"{f}"
    except (ValueError, TypeError):
        return str(v)


def _layers_html(sample):
    """Re-render description from layers[] if split; else top-level description."""
    layers = _loads(sample.get("layers"), None)
    if layers and isinstance(layers, list) and layers:
        chunks = []
        for lf in layers:
            ds = lf.get("depth_start")
            de = lf.get("depth_end")
            d = _xml_escape((lf.get("description") or "").strip())
            if ds is not None and de is not None:
                chunks.append(f"<b>{_fmt_num(ds)}–{_fmt_num(de)} in:</b> {d}")
            else:
                chunks.append(d)
        return "<br/><br/>".join(chunks)
    return _xml_escape(sample.get("description") or "").replace("\n", "<br/>")


def _comments_html(sample):
    parts = []
    cmt = _xml_escape((sample.get("comments") or "").strip())
    if cmt:
        parts.append(cmt)
    flags = _loads(sample.get("flags"), []) or []
    for f in flags:
        parts.append(f'<font color="{FLAG_HEX}"><b>[FLAG]</b></font> {_xml_escape(f)}')
    return "<br/>".join(parts)


# ── Column geometry ──

def _build_col_x():
    out = {}
    x = MARGIN
    for name in COL_ORDER:
        w = COL_WIDTHS[name]
        out[name] = (x, w)
        x += w
    return out


COLS = _build_col_x()


# ── Header drawing ──

def _draw_full_header(c, project, borehole):
    """Draws boxed project/borehole header on page 1. Returns y where log area starts."""
    top = PAGE_H - MARGIN
    bottom = top - FULL_HEADER_H

    # Outer border
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
        f"BORING LOG  —  {borehole.get('borehole_no') or ''}",
    )
    c.setFillColor(colors.black)

    # Hammer combo
    hw = borehole.get("hammer_weight")
    hd = borehole.get("hammer_drop")
    if hw and hd:
        hammer = f"{hw} lbs / {hd} in"
    elif hw:
        hammer = f"{hw} lbs"
    elif hd:
        hammer = f"{hd} in"
    else:
        hammer = ""

    left_fields = [
        ("Project No",  project.get("project_no") or ""),
        ("Client",      project.get("client") or ""),
        ("Location",    project.get("location") or ""),
        ("Date",        borehole.get("date_started") or ""),
    ]
    right_fields = [
        ("Borehole ID",       borehole.get("borehole_no") or ""),
        ("Driller",           borehole.get("driller") or ""),
        ("Drilling Method",   borehole.get("drilling_method") or ""),
        ("Hammer Wt / Drop",  hammer),
    ]

    field_top = top - title_h - 0.18 * inch
    line_h = 0.24 * inch
    label_w = 0.95 * inch
    half_w = USABLE_W / 2
    value_w = half_w - label_w - 16

    def _draw_col(fields, col_x):
        for i, (label, value) in enumerate(fields):
            y = field_top - i * line_h
            c.setFont("Helvetica-Bold", FS_HDR_LABEL)
            c.drawString(col_x, y, f"{label}:")
            c.setFont("Helvetica", FS_HDR_VALUE)
            c.drawString(col_x + label_w, y, value or "")
            c.setStrokeColor(BORDER)
            c.setLineWidth(0.4)
            c.line(col_x + label_w, y - 1.5,
                   col_x + label_w + value_w, y - 1.5)

    _draw_col(left_fields,  MARGIN + 8)
    _draw_col(right_fields, MARGIN + half_w + 4)

    # Vertical divider down the middle of the field area
    c.setStrokeColor(BORDER)
    c.setLineWidth(0.4)
    c.line(MARGIN + half_w, top - title_h - 4,
           MARGIN + half_w, bottom + 4)

    return bottom - FULL_HEADER_GAP


def _draw_compact_header(c, project, borehole, page_num, depth_top, depth_bot):
    """Slim repeated header for pages 2+. Returns y where log area starts."""
    top = PAGE_H - MARGIN
    bottom = top - COMPACT_HEADER_H

    c.setStrokeColor(BORDER_HEAVY)
    c.setLineWidth(0.6)
    c.rect(MARGIN, bottom, USABLE_W, COMPACT_HEADER_H, stroke=1, fill=0)

    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 9)
    text = (
        f"Project {project.get('project_no') or ''}   |   "
        f"Borehole {borehole.get('borehole_no') or ''}   |   "
        f"Page {page_num}   |   "
        f"Depth {_fmt_num(depth_top)}–{_fmt_num(depth_bot)} ft"
    )
    c.drawString(MARGIN + 8, bottom + 8, text)

    return bottom - COMPACT_HEADER_GAP


# ── Column header row ──

def _draw_column_headers(c, y_top):
    bottom = y_top - COL_HDR_HEIGHT

    c.setFillColor(HEADER_BG)
    c.rect(MARGIN, bottom, USABLE_W, COL_HDR_HEIGHT, stroke=0, fill=1)

    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", FS_BODY)
    for name in COL_ORDER:
        x, w = COLS[name]
        label = COL_LABELS[name]
        tw = c.stringWidth(label, "Helvetica-Bold", FS_BODY)
        c.drawString(x + (w - tw) / 2, bottom + 5, label)

    # white separators between header cells
    c.setStrokeColor(colors.white)
    c.setLineWidth(0.4)
    for name in COL_ORDER[1:]:
        x, _ = COLS[name]
        c.line(x, bottom, x, y_top)

    c.setFillColor(colors.black)
    return bottom


# ── Depth scale + body framework ──

def _draw_body_frame(c, body_top_y, body_bot_y, page_depth_top, page_depth_bot):
    """Outer body box, depth ticks, vertical column separators."""
    body_h = body_top_y - body_bot_y

    c.setStrokeColor(BORDER)
    c.setLineWidth(0.4)
    c.rect(MARGIN, body_bot_y, USABLE_W, body_h, stroke=1, fill=0)

    # Vertical separators between every column
    for name in COL_ORDER[1:]:
        x, _ = COLS[name]
        c.line(x, body_top_y, x, body_bot_y)

    # Depth ticks every 1 ft (and 0.5 ft minor)
    dx, dw = COLS["depth"]
    c.setFont("Helvetica", FS_DEPTH)
    c.setFillColor(colors.black)

    # First whole-foot tick at or after page top
    if page_depth_top == int(page_depth_top):
        ft = int(page_depth_top)
    else:
        ft = int(page_depth_top) + 1

    while ft <= page_depth_bot + 1e-6:
        y = body_top_y - (ft - page_depth_top) * SCALE_PT_PER_FT
        if y < body_bot_y - 1e-6:
            break
        c.setStrokeColor(BORDER)
        c.setLineWidth(0.4)
        c.line(dx, y, dx + dw * 0.30, y)
        c.drawString(dx + dw * 0.36, y - FS_DEPTH / 2 + 1, str(ft))
        ft += 1

    # Minor 0.5 ft ticks
    half = page_depth_top
    if (half * 2) == int(half * 2):
        # already on a 0.5 boundary; advance by 0.5 to first interior tick
        half += 0.5
    else:
        # next 0.5 boundary
        half = (int(half * 2) + 1) / 2.0
    while half <= page_depth_bot + 1e-6:
        if half != int(half):
            y = body_top_y - (half - page_depth_top) * SCALE_PT_PER_FT
            if y >= body_bot_y:
                c.setStrokeColor(BORDER)
                c.setLineWidth(0.3)
                c.line(dx, y, dx + dw * 0.15, y)
        half += 0.5


# ── Sample drawing ──

def _draw_sample(c, sample, top_ft, bot_ft, page_depth_top, page_depth_bot, body_top_y):
    """Draw one sample's portion that falls within the page's depth window."""
    visible_top_ft = max(top_ft, page_depth_top)
    visible_bot_ft = min(bot_ft, page_depth_bot)
    if visible_bot_ft <= visible_top_ft + 1e-9:
        return

    y_top = body_top_y - (visible_top_ft - page_depth_top) * SCALE_PT_PER_FT
    y_bot = body_top_y - (visible_bot_ft - page_depth_top) * SCALE_PT_PER_FT
    box_h = y_top - y_bot

    # Render text columns (description, sample id, n, rec, comments) only on
    # the page where the sample's top first appears; skip on continuation pages.
    is_first_page_of_sample = (top_ft >= page_depth_top - 1e-9)

    # Highlight tint behind the sample column for the visible interval
    sx, sw = COLS["sample"]
    c.setFillColor(SAMPLE_HIGHLIGHT)
    c.rect(sx, y_bot, sw, box_h, stroke=0, fill=1)

    # Top & bottom horizontal rules for this sample (across full body width)
    c.setStrokeColor(BORDER)
    c.setLineWidth(0.5)
    c.line(MARGIN, y_top, MARGIN + USABLE_W, y_top)
    c.line(MARGIN, y_bot, MARGIN + USABLE_W, y_bot)

    if is_first_page_of_sample:
        # Sample ID (top of sample box)
        st = sample.get("sample_type")
        sn = sample.get("sample_no")
        if st and sn is not None:
            sample_label = f"{st}-{sn}"
        elif sn is not None:
            sample_label = str(sn)
        else:
            sample_label = ""
        if sample_label:
            c.setFillColor(colors.black)
            c.setFont("Helvetica-Bold", FS_BODY + 1)
            tw = c.stringWidth(sample_label, "Helvetica-Bold", FS_BODY + 1)
            c.drawString(sx + (sw - tw) / 2, y_top - 11, sample_label)

        # Description
        dx, dw = COLS["desc"]
        desc_html = _layers_html(sample) or "&nbsp;"
        para = Paragraph(desc_html, DESC_STYLE)
        avail_w = dw - 8
        avail_h = box_h - 4
        para.wrapOn(c, avail_w, avail_h)
        # anchor at top of sample box
        para.drawOn(c, dx + 4, y_top - para.height - 2)

        # N-value (centered vertically in sample box)
        nx, nw = COLS["n"]
        n = sample.get("n_value")
        if n is not None:
            c.setFillColor(colors.black)
            c.setFont("Helvetica-Bold", FS_BODY)
            txt = str(n)
            tw = c.stringWidth(txt, "Helvetica-Bold", FS_BODY)
            c.drawString(
                nx + (nw - tw) / 2,
                y_bot + (box_h - FS_BODY) / 2 + 1,
                txt,
            )

        # Recovery (centered vertically in sample box)
        rx, rw = COLS["rec"]
        rec = sample.get("recovery_inches")
        if rec is not None:
            c.setFillColor(colors.black)
            c.setFont("Helvetica", FS_BODY)
            txt = _fmt_num(rec)
            tw = c.stringWidth(txt, "Helvetica", FS_BODY)
            c.drawString(
                rx + (rw - tw) / 2,
                y_bot + (box_h - FS_BODY) / 2 + 1,
                txt,
            )

        # Comments / Flags
        cx, cw = COLS["comments"]
        cmt_html = _comments_html(sample)
        if cmt_html:
            para = Paragraph(cmt_html, COMMENT_STYLE)
            para.wrapOn(c, cw - 8, box_h - 4)
            para.drawOn(c, cx + 4, y_top - para.height - 2)

    # Blow-count stack (always; per-increment visibility handled below)
    bx, bw = COLS["blows"]
    blow_counts = _loads(sample.get("blow_counts"), []) or []
    pen_depths = _loads(sample.get("pen_depths"), []) or []

    cur_ft = top_ft
    for i, bc in enumerate(blow_counts):
        pd = pen_depths[i] if i < len(pen_depths) else 6
        try:
            pd_f = float(pd)
        except (TypeError, ValueError):
            pd_f = 6.0
        inc_top_ft = cur_ft
        inc_bot_ft = cur_ft + (pd_f / 12.0)
        cur_ft = inc_bot_ft

        v_top = max(inc_top_ft, page_depth_top)
        v_bot = min(inc_bot_ft, page_depth_bot)
        if v_bot <= v_top + 1e-9:
            continue

        iy_top = body_top_y - (v_top - page_depth_top) * SCALE_PT_PER_FT
        iy_bot = body_top_y - (v_bot - page_depth_top) * SCALE_PT_PER_FT
        ih = iy_top - iy_bot

        c.setStrokeColor(BORDER)
        c.setLineWidth(0.4)
        c.rect(bx, iy_bot, bw, ih, stroke=1, fill=0)

        # Only draw value text if the increment is fully visible on this page
        fully_visible = (
            inc_top_ft >= page_depth_top - 1e-9
            and inc_bot_ft <= page_depth_bot + 1e-9
        )
        if fully_visible:
            if pd_f == 6:
                txt = str(bc)
            else:
                txt = f"{bc}/{_fmt_num(pd_f)}\""
            c.setFillColor(colors.black)
            c.setFont("Helvetica", FS_BODY)
            tw = c.stringWidth(txt, "Helvetica", FS_BODY)
            c.drawString(
                bx + (bw - tw) / 2,
                iy_bot + (ih - FS_BODY) / 2 + 1,
                txt,
            )


# ── Data fetch ──

def _fetch_project(project_id):
    r = (
        supabase_client.table("projects")
        .select("*")
        .eq("id", project_id)
        .limit(1)
        .execute()
    )
    if not r.data:
        raise ValueError(f"Project {project_id} not found")
    return r.data[0]


def _fetch_borehole(project_id, borehole_id):
    r = (
        supabase_client.table("boreholes")
        .select("*")
        .eq("id", borehole_id)
        .eq("project_id", project_id)
        .limit(1)
        .execute()
    )
    if not r.data:
        raise ValueError(f"Borehole {borehole_id} not found in project {project_id}")
    return r.data[0]


def _fetch_samples(project_id, borehole_id):
    r = (
        supabase_client.table("samples")
        .select("*")
        .eq("project_id", project_id)
        .eq("borehole_id", borehole_id)
        .order("depth_ft", desc=False)
        .execute()
    )
    return r.data or []


# ── Main entry point ──

def generate_boring_log(project_id: int, borehole_id: int) -> bytes:
    project = _fetch_project(project_id)
    borehole = _fetch_borehole(project_id, borehole_id)
    samples = _fetch_samples(project_id, borehole_id)

    if not samples:
        raise ValueError(f"No samples for borehole {borehole_id}")

    buf = io.BytesIO()

    # Build vertical intervals: depth_ft = top of sample; length comes from
    # sum(pen_depths)/12. Gaps between samples represent auger advance.
    intervals = []
    for s in samples:
        try:
            top = float(s.get("depth_ft") or 0)
        except (TypeError, ValueError):
            top = 0.0
        pen_depths = _loads(s.get("pen_depths"), []) or []
        length_in = 0.0
        for p in pen_depths:
            try:
                length_in += float(p)
            except (TypeError, ValueError):
                pass
        bot = top + (length_in / 12.0)
        intervals.append((top, bot, s))
    total_depth = max((b for _, b, _ in intervals), default=0.0)

    c = canvas.Canvas(buf, pagesize=letter)
    c.setTitle(f"Boring Log {borehole.get('borehole_no') or ''}")

    page_num = 1
    depth_top = 0.0

    while depth_top < total_depth - 1e-9:
        # Estimate body capacity to compute this page's depth range first
        if page_num == 1:
            header_total = FULL_HEADER_H + FULL_HEADER_GAP
        else:
            header_total = COMPACT_HEADER_H + COMPACT_HEADER_GAP
        body_h_max = (PAGE_H - MARGIN) - header_total - COL_HDR_HEIGHT - MARGIN
        depth_per_page = body_h_max / SCALE_PT_PER_FT
        depth_bot = min(depth_top + depth_per_page, total_depth)

        # Draw header
        if page_num == 1:
            header_bottom = _draw_full_header(c, project, borehole)
        else:
            header_bottom = _draw_compact_header(
                c, project, borehole, page_num, depth_top, depth_bot
            )

        # Column headers
        col_hdr_bottom = _draw_column_headers(c, header_bottom)

        # Body extent for this page (shrink on last page so we don't draw an empty tail)
        body_top_y = col_hdr_bottom
        body_bot_y = body_top_y - (depth_bot - depth_top) * SCALE_PT_PER_FT

        _draw_body_frame(c, body_top_y, body_bot_y, depth_top, depth_bot)

        for top_ft, bot_ft, sample in intervals:
            if bot_ft <= depth_top + 1e-9 or top_ft >= depth_bot - 1e-9:
                continue
            _draw_sample(c, sample, top_ft, bot_ft, depth_top, depth_bot, body_top_y)

        # Page footer
        c.setFillColor(colors.grey)
        c.setFont("Helvetica", 7)
        c.drawRightString(PAGE_W - MARGIN, MARGIN - 12, f"Page {page_num}")
        c.setFillColor(colors.black)

        c.showPage()
        depth_top = depth_bot
        page_num += 1

    c.save()
    return buf.getvalue()


if __name__ == "__main__":
    # Replace with a real project_id and borehole_id from your DB
    pdf_bytes = generate_boring_log(project_id=1, borehole_id=1)
    with open("test_output.pdf", "wb") as f:
        f.write(pdf_bytes)
    print("PDF written to test_output.pdf")
