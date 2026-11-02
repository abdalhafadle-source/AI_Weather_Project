#!/usr/bin/env python3
"""
build_report.py
Build the final thesis report (Arabic, right-to-left Word file) from thesis/report_content.py
and the figures in thesis/figures/.

Usage:
    python thesis/build_report.py        # writes thesis/Hilla_PV_AI_Report.docx
Afterwards Word fills the table of contents (Ctrl+A then F9), or update_and_pdf.ps1 does it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

sys.path.insert(0, str(Path(__file__).parent))
from report_content import CONTENT  # noqa: E402

HERE = Path(__file__).parent
FIG = HERE / "figures"
OUT = HERE / "Hilla_PV_AI_Report.docx"
FONT = "Arial"
_fig_no = [0]
_tab_no = [0]


def _el(tag, **attrs):
    e = OxmlElement(tag)
    for k, v in attrs.items():
        e.set(qn(k), v)
    return e


def rtl_par(p):
    # paragraph direction right-to-left (inserted in schema order)
    pPr = p._p.get_or_add_pPr()
    if pPr.find(qn("w:bidi")) is None:
        pPr.insert_element_before(_el("w:bidi"), "w:adjustRightInd", "w:snapToGrid", "w:spacing", "w:ind",
                                  "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc",
                                  "w:textDirection", "w:textAlignment", "w:textboxTightWrap", "w:outlineLvl",
                                  "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange")


# an English phrase (with its brackets) inside Arabic text: kept as one left-to-right run so brackets don't flip
LATIN = re.compile(r"\(?[A-Za-z][A-Za-z0-9 .,:;/_+\-=&'’%°µ³²#@()\[\]]*[A-Za-z0-9%°³²)\]]|\(?[A-Za-z]\)?")


def style_run(r, size=None, bold=None, italic=None, color=None, mono=False, ltr=False):
    rPr = r._r.get_or_add_rPr()
    fonts = rPr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = _el("w:rFonts")
        rPr.insert(0, fonts)
    name = "Consolas" if mono else FONT
    for a in ("w:ascii", "w:hAnsi", "w:cs"):
        fonts.set(qn(a), name)
    if not (mono or ltr):
        rPr.append(_el("w:rtl"))
    if size:
        r.font.size = Pt(size)
        rPr.append(_el("w:szCs", **{"w:val": str(int(size * 2))}))
    if bold:
        r.bold = True
        rPr.append(_el("w:bCs"))
    if italic:
        r.italic = True
    if color:
        r.font.color.rgb = RGBColor.from_string(color)


def add_mixed(p, text, **kw):
    # Arabic pieces right-to-left, English pieces left-to-right
    pos = 0
    for m in LATIN.finditer(text):
        if m.start() > pos:
            style_run(p.add_run(text[pos:m.start()]), **kw)
        style_run(p.add_run(m.group()), ltr=True, **kw)
        pos = m.end()
    if pos < len(text):
        style_run(p.add_run(text[pos:]), **kw)


def add_text(p, text, size=None, color=None, italic=None):
    # **bold** and `code` inline markup
    for part in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text):
        if not part:
            continue
        if part.startswith("**"):
            add_mixed(p, part[2:-2], size=size, bold=True, color=color, italic=italic)
        elif part.startswith("`"):
            style_run(p.add_run(part[1:-1]), size=(size or 11) - 1, mono=True, color="1F4E79")
        else:
            add_mixed(p, part, size=size, color=color, italic=italic)


def para(doc, text, align=WD_ALIGN_PARAGRAPH.JUSTIFY, size=None, color=None, italic=None, space_after=6, style=None):
    p = doc.add_paragraph(style=style)
    rtl_par(p)
    p.alignment = align
    p.paragraph_format.space_after = Pt(space_after)
    add_text(p, text, size=size, color=color, italic=italic)
    return p


def heading(doc, text, level):
    h = doc.add_heading(level=level)
    rtl_par(h)
    h.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    style_run(h.add_run(text), size={1: 18, 2: 15, 3: 13}[level], bold=True, color="1F3864")
    return h


def bullets(doc, items, numbered=False):
    for i, it in enumerate(items, 1):
        p = doc.add_paragraph(style="List Number" if numbered else "List Bullet")
        rtl_par(p)
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.paragraph_format.space_after = Pt(3)
        add_text(p, it)


def shade(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    tcPr.append(_el("w:shd", **{"w:val": "clear", "w:color": "auto", "w:fill": fill}))


def table(doc, header, rows, caption=None, widths=None, size=10):
    if caption:
        _tab_no[0] += 1
        para(doc, f"**جدول {_tab_no[0]}:** {caption}", align=WD_ALIGN_PARAGRAPH.CENTER, size=10, space_after=2)
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    tblPr = t._tbl.tblPr
    tblPr.insert_element_before(_el("w:bidiVisual"), "w:tblStyleRowBandSize", "w:tblStyleColBandSize", "w:tblW",
                                "w:jc", "w:tblCellSpacing", "w:tblInd", "w:tblBorders", "w:shd", "w:tblLayout",
                                "w:tblCellMar", "w:tblLook")
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]
        c.paragraphs[0].text = ""
        rtl_par(c.paragraphs[0])
        add_text(c.paragraphs[0], f"**{h}**", size=size)
        shade(c, "E7ECF3")
    trPr = t.rows[0]._tr.get_or_add_trPr()
    trPr.append(_el("w:tblHeader"))
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            p = cells[i].paragraphs[0]
            rtl_par(p)
            add_text(p, str(v), size=size)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(4)


def figure(doc, name, caption, width=15.5):
    path = FIG / name
    if not path.exists():
        para(doc, f"[الشكل غير موجود: {name}]", color="C00000")
        return
    _fig_no[0] += 1
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run().add_picture(str(path), width=Cm(width))
    para(doc, f"**الشكل {_fig_no[0]}:** {caption}", align=WD_ALIGN_PARAGRAPH.CENTER, size=10, italic=False,
         color="404040", space_after=10)


def code(doc, text):
    for line in text.strip("\n").split("\n"):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        pPr = p._p.get_or_add_pPr()
        pPr.append(_el("w:shd", **{"w:val": "clear", "w:color": "auto", "w:fill": "F2F2F2"}))
        style_run(p.add_run(line or " "), size=9.5, mono=True)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def note(doc, text):
    p = para(doc, text, size=10.5, color="3A3A3A")
    pPr = p._p.get_or_add_pPr()
    pPr.append(_el("w:shd", **{"w:val": "clear", "w:color": "auto", "w:fill": "FFF7E0"}))


def toc(doc):
    p = doc.add_paragraph()
    r = p.add_run()
    for tag, extra in (("begin", None), ("instr", 'TOC \\o "1-2" \\h \\z \\u'), ("separate", None), ("end", None)):
        if tag == "instr":
            it = _el("w:instrText", **{"xml:space": "preserve"})
            it.text = extra
            r._r.append(it)
        else:
            r._r.append(_el("w:fldChar", **{"w:fldCharType": tag}))
            if tag == "separate":
                t = _el("w:t")
                t.text = "اضغط Ctrl+A ثم F9 لتحديث جدول المحتويات"
                r._r.append(t)


def page_numbers(section):
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run()
    r._r.append(_el("w:fldChar", **{"w:fldCharType": "begin"}))
    it = _el("w:instrText", **{"xml:space": "preserve"})
    it.text = "PAGE"
    r._r.append(it)
    r._r.append(_el("w:fldChar", **{"w:fldCharType": "end"}))


def setup(doc):
    s = doc.sections[0]
    s.page_height, s.page_width = Cm(29.7), Cm(21.0)
    s.left_margin = s.right_margin = Cm(2.3)
    s.top_margin = s.bottom_margin = Cm(2.2)
    sectPr = s._sectPr
    sectPr.append(_el("w:bidi"))
    page_numbers(s)
    for name in ("Normal", "List Bullet", "List Number", "Heading 1", "Heading 2", "Heading 3"):
        st = doc.styles[name]
        rPr = st.element.get_or_add_rPr()
        fonts = rPr.find(qn("w:rFonts"))
        if fonts is None:
            fonts = _el("w:rFonts")
            rPr.insert(0, fonts)
        for a in ("w:ascii", "w:hAnsi", "w:cs"):
            fonts.set(qn(a), FONT)
        for a in ("w:asciiTheme", "w:hAnsiTheme", "w:cstheme", "w:eastAsiaTheme"):
            if fonts.get(qn(a)) is not None:
                del fonts.attrib[qn(a)]
        rPr.append(_el("w:lang", **{"w:bidi": "ar-IQ"}))
    doc.styles["Normal"].font.size = Pt(12)
    doc.styles["Normal"].element.get_or_add_rPr().append(_el("w:szCs", **{"w:val": "24"}))


def main() -> int:
    doc = Document()
    setup(doc)
    for block in CONTENT:
        kind, *a = block
        if kind == "title":
            para(doc, a[0], align=WD_ALIGN_PARAGRAPH.CENTER, size=a[1] if len(a) > 1 else 22, space_after=8)
        elif kind == "h1":
            heading(doc, a[0], 1)
        elif kind == "h2":
            heading(doc, a[0], 2)
        elif kind == "h3":
            heading(doc, a[0], 3)
        elif kind == "p":
            para(doc, a[0])
        elif kind == "center":
            para(doc, a[0], align=WD_ALIGN_PARAGRAPH.CENTER)
        elif kind == "bullets":
            bullets(doc, a[0])
        elif kind == "numbered":
            bullets(doc, a[0], numbered=True)
        elif kind == "table":
            table(doc, a[0], a[1], caption=a[2] if len(a) > 2 else None, widths=a[3] if len(a) > 3 else None)
        elif kind == "fig":
            figure(doc, a[0], a[1], width=a[2] if len(a) > 2 else 15.5)
        elif kind == "code":
            code(doc, a[0])
        elif kind == "note":
            note(doc, a[0])
        elif kind == "toc":
            toc(doc)
        elif kind == "pagebreak":
            doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        else:
            raise ValueError(f"unknown block {kind}")
    doc.save(OUT)
    print(f"saved {OUT}   figures: {_fig_no[0]}   tables: {_tab_no[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
