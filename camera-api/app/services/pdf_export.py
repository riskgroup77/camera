"""Filtr natijalarini PDF qilib yuklab olish — umumiy jadval hujjati.

Har PDF bir xil ko'rinishda: muassasa nomi, hujjat sarlavhasi, sana va
yaratilgan vaqt, qaysi filtrlar tanlangani, sanoqlar qatori va jadval
(sarlavhasi har sahifada takrorlanadi), pastda sahifa raqami.

Shrift: DejaVu Sans (Docker obrazida fonts-dejavu-core) — o'zbek lotinidagi
ʻ/‘ va kirill harflari shunda to'g'ri chiqadi. Shrift topilmasa (masalan
mahalliy test) — Helvetica, maxsus belgilar oddiy apostrofga almashtiriladi.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass, field
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

from app.config import settings
from app.timezone import local_now

_FONT_CANDIDATES = (
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
)
_font: tuple[str, str, bool] | None = None
_APOS = str.maketrans({c: "'" for c in "‘’ʻʼ`´"})


def _fonts() -> tuple[str, str, bool]:
    """(oddiy, qalin, unicode) — bir marta ro'yxatdan o'tkaziladi."""
    global _font
    if _font is not None:
        return _font
    for regular, bold in _FONT_CANDIDATES:
        if os.path.exists(regular) and os.path.exists(bold):
            try:
                pdfmetrics.registerFont(TTFont("DocSans", regular))
                pdfmetrics.registerFont(TTFont("DocSans-Bold", bold))
                _font = ("DocSans", "DocSans-Bold", True)
                return _font
            except Exception:  # noqa: BLE001 — buzilgan shrift fayli: keyingisi
                continue
    _font = ("Helvetica", "Helvetica-Bold", False)
    return _font


def _text(value: object) -> str:
    text = "" if value is None else str(value)
    if not _fonts()[2]:
        text = text.translate(_APOS).encode("latin-1", "replace").decode("latin-1")
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


@dataclass
class PdfColumn:
    header: str
    width: float  # nisbiy kenglik
    align: str = "LEFT"


@dataclass
class PdfDocument:
    title: str
    columns: list[PdfColumn]
    rows: list[list[object]]
    filters: list[tuple[str, str]] = field(default_factory=list)
    counts: list[tuple[str, object]] = field(default_factory=list)
    note: str | None = None
    # Qator rangi (holat bo'yicha) — ixtiyoriy: satr indeksi -> rang.
    row_tones: dict[int, str] = field(default_factory=dict)


TONES = {
    "success": colors.HexColor("#e7f6ee"),
    "warning": colors.HexColor("#fff4e0"),
    "danger": colors.HexColor("#fdecec"),
}


def render(document: PdfDocument, *, generated: datetime | None = None) -> bytes:
    regular, bold, _unicode = _fonts()
    buffer = io.BytesIO()
    page = landscape(A4)
    margin = 12 * mm
    doc = SimpleDocTemplate(
        buffer, pagesize=page, leftMargin=margin, rightMargin=margin, topMargin=margin, bottomMargin=14 * mm,
        title=document.title, author=settings.org_name,
    )
    base = ParagraphStyle("base", fontName=regular, fontSize=8.5, leading=10.5, alignment=TA_LEFT)
    head = ParagraphStyle("head", parent=base, fontName=bold, fontSize=8.5, textColor=colors.white)
    small = ParagraphStyle("small", parent=base, fontSize=8, textColor=colors.HexColor("#555f73"))
    title = ParagraphStyle("title", parent=base, fontName=bold, fontSize=14, leading=18)
    moment = generated or local_now()

    story: list = [
        Paragraph(_text(settings.org_name), small),
        Paragraph(_text(document.title), title),
        Paragraph(_text(f"Yaratildi: {moment:%d.%m.%Y %H:%M}"), small),
    ]
    if document.filters:
        story.append(Paragraph(_text("Filtr: " + " · ".join(f"{k}: {v}" for k, v in document.filters)), small))
    if document.counts:
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(_text("  ·  ".join(f"{k}: {v}" for k, v in document.counts)),
                               ParagraphStyle("counts", parent=base, fontName=bold, fontSize=9.5)))
    if document.note:
        story.append(Paragraph(_text(document.note), small))
    story.append(Spacer(1, 3 * mm))

    usable = page[0] - 2 * margin
    total = sum(c.width for c in document.columns) or 1
    widths = [usable * c.width / total for c in document.columns]
    data = [[Paragraph(_text(c.header), head) for c in document.columns]]
    # Uslublar bir marta: ilgari har katak uchun yangi ParagraphStyle
    # yaratilardi (5000 qator × 8 ustun = 40 000 ta).
    cell_styles = [
        ParagraphStyle(f"c{i}", parent=base, alignment={"RIGHT": 2, "CENTER": 1}.get(col.align, 0))
        for i, col in enumerate(document.columns)
    ]
    for row in document.rows:
        data.append([
            Paragraph(_text(value), cell_styles[i])
            for i, (value, _col) in enumerate(zip(row, document.columns, strict=True))
        ])
    if len(data) == 1:
        data.append([Paragraph(_text("Ma'lumot yo'q"), small)] + [""] * (len(document.columns) - 1))

    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2d53de")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c9d2e3")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f8fc")]),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]
    for index, tone in document.row_tones.items():
        if tone in TONES:
            style.append(("BACKGROUND", (0, index + 1), (-1, index + 1), TONES[tone]))
    table = LongTable(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle(style))
    story.append(table)

    def footer(canvas, _doc):
        canvas.saveState()
        canvas.setFont(regular, 7.5)
        canvas.setFillColor(colors.HexColor("#7a8499"))
        canvas.drawString(margin, 8 * mm, _plain(f"{settings.org_name} · {document.title}"))
        canvas.drawRightString(page[0] - margin, 8 * mm, f"{_doc.page}-sahifa")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def _plain(text: str) -> str:
    if _fonts()[2]:
        return text
    return text.translate(_APOS).encode("latin-1", "replace").decode("latin-1")


def filename(stem: str, day: str | None = None) -> str:
    # HTTP sarlavhasi — faqat ASCII (kirill guruh nomi sarlavhani buzardi).
    safe = "".join(ch if (ch.isascii() and ch.isalnum()) or ch in "-_" else "-" for ch in stem.lower()).strip("-") or "hisobot"
    return f"{safe}-{day}.pdf" if day else f"{safe}.pdf"


async def render_async(document: PdfDocument) -> bytes:
    """render() alohida oqimda: katta PDF (minglab qator) CPU ishi — asosiy
    hodisa siklida bajarilsa, shu jarayondagi barcha so'rovlar (leader'da
    AI tekshiruvlari ham) soniyalab qotib qolardi."""
    import asyncio

    return await asyncio.to_thread(render, document)
