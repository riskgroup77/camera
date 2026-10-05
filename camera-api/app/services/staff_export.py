"""Talabalar va xodimlar ro'yxatini Excel (.xlsx) faylga chiqarish.

NIMA UCHUN CSV EMAS. Avval ro'yxat ";" ajratgichli CSV bo'lib yuklanardi
va Excel'da ma'lumotlar aralashib ochilardi. Sabab formatning o'zida:
CSV'da ustun ajratgichi fayl ichida yozilmaydi, Excel uni kompyuterning
til sozlamasidan TAXMIN qiladi. Ingliz lokalida u "," kutadi — va ";"
bilan ajratilgan butun qator bitta katakka tushadi. Buni fayl tomonidan
tuzatib bo'lmaydi; .xlsx esa ustunlarni o'zi saqlaydi va har qanday
kompyuterda bir xil ochiladi.

JSHSHIR MATN SIFATIDA. Excel 14 xonali raqamni son deb o'qiydi va uni
3,03027E+13 ko'rinishida ko'rsatadi, oxirgi xonalarni esa yo'qotadi. Nol
bilan boshlanadigan raqam (masalan sinov hisobi 00000000000000) esa
shunchaki 0 bo'lib qoladi. Shuning uchun JSHSHIR katagi matn formatida
yoziladi.

TALABA VA XODIM ALOHIDA. Ikkalasi bitta jadvalda aralash turganda
talabaning kursi va guruhi "2-kurs, DI-1625" degan bitta matn bo'lib,
xodimning kafedrasi bilan bir ustunga tushardi — na kurs bo'yicha
saralab, na filtrlab bo'lardi. Endi har bir tur o'z ustunlari bilan
chiqadi: talabada Kurs va Guruh, xodimda Kafedra / Bo'lim.

Ikki xil fayl bor va ular turli savolga javob beradi:

  build_people_workbook — "kim": har bir odam alohida qator, tanlangan
  filtr bo'yicha. Guruh rahbariga "guruhingizdan kim qoldi" deb yuborish
  uchun.

  build_stats_workbook — "qancha": fakultet, kurs, guruh yoki kafedra
  kesimida qamrov. Rahbariyatga "jarayon qayerda orqada" deb ko'rsatish
  uchun.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

NAVY = "1F3864"
ZEBRA = "F5F7FB"
BORDER_COLOR = "C9D1E0"

STATUS_LABELS = {
    "tasdiqlangan": "Tasdiqlangan",
    "kutilmoqda": "Kutilmoqda",
    "yoq": "Tasdiqlanmagan",
}

#: Holat katagining foni — ro'yxatni ko'z bilan tez ko'zdan kechirish uchun.
STATUS_FILLS = {
    "tasdiqlangan": "D9F2E3",
    "kutilmoqda": "FFF1CC",
    "yoq": "FBE0E0",
}

NO_FACULTY_LABEL = "Fakultetsiz"
COURSE_UNKNOWN_LABEL = "Kurs ko'rsatilmagan"

_thin = Side(style="thin", color=BORDER_COLOR)
_BORDER = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)
_HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
_HEADER_FILL = PatternFill("solid", fgColor=NAVY)
_WRAP = Alignment(vertical="center", wrap_text=True)
_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)

_COURSE_RE = re.compile(r"^\s*(\d{1,2})\s*-\s*kurs\b\s*,?\s*(.*)$", re.IGNORECASE)


def split_course(group_or_position: str | None) -> tuple[int | None, str]:
    """"2-kurs, DI-1625" -> (2, "DI-1625"); "4-kurs" -> (4, "");
    kurs ko'rsatilmagan matn -> (None, o'zi).

    Talaba importi kurs va guruhni group_or_position'ga shu shaklda
    yozadi (scripts/import_talabalar.py). Alohida ustun qo'shish o'rniga
    shu yerda ajratiladi: qo'lda kiritilgan eski yozuvlar ham buzilmaydi."""
    text = (group_or_position or "").strip()
    match = _COURSE_RE.match(text)
    if not match:
        return None, text
    return int(match.group(1)), match.group(2).strip()


def course_label(course: int | None) -> str:
    return f"{course}-kurs" if course else COURSE_UNKNOWN_LABEL


# ─────────────────────────────────────────── umumiy yordamchilar

def _title(ws: Worksheet, text: str, subtitle: str, width: int) -> None:
    """1-qator sarlavha, 2-qator izoh; ikkalasi ham jadval kengligida."""
    last = get_column_letter(width)
    ws.merge_cells(f"A1:{last}1")
    ws["A1"] = text
    ws["A1"].font = Font(bold=True, size=15, color=NAVY)
    ws["A1"].alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 26

    ws.merge_cells(f"A2:{last}2")
    ws["A2"] = subtitle
    ws["A2"].font = Font(italic=True, size=10, color="5A6472")
    ws["A2"].alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[2].height = 30


def _header(ws: Worksheet, row: int, headers: list[str]) -> None:
    for col, text in enumerate(headers, 1):
        cell = ws.cell(row=row, column=col, value=text)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = _CENTER
        cell.border = _BORDER
    ws.row_dimensions[row].height = 30


def _widths(ws: Worksheet, widths: list[float]) -> None:
    for col, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(col)].width = width


def _landscape(ws: Worksheet, header_row: int) -> None:
    """Chop etilganda ham o'qiladigan bo'lsin: albom, kenglikka sig'dirish,
    sarlavha har sahifada takrorlanadi."""
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = f"{header_row}:{header_row}"


def _to_bytes(wb: Workbook) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _stamp(now: datetime) -> str:
    return now.strftime("%d.%m.%Y %H:%M")


# ─────────────────────────────────────────── 1. Ro'yxat

@dataclass(frozen=True)
class PersonRow:
    full_name: str
    pinfl: str
    type: str
    faculty: str
    unit: str  # group_or_position — talabada "2-kurs, DI-1625", xodimda kafedra
    biometrics_status: str
    confirmed_at: str = ""  # "14.09.2026 13:57", Toshkent vaqti; bo'sh — yozilmagan


def person_sort_key(row: PersonRow) -> tuple:
    """Fakultet (fakultetsizlar oxirida) -> kurs -> guruh/kafedra -> ism.
    Faylni guruhlarga bo'lib tarqatish shu tartibda qulay."""
    course, group = split_course(row.unit)
    return (
        row.faculty == NO_FACULTY_LABEL,
        row.faculty.lower(),
        course or 99,
        group.lower(),
        row.full_name.lower(),
    )


def _people_columns(person_type: str | None):
    """(varaq nomi, sarlavhalar, kengliklar, qiymat funksiyasi, markazlanadigan ustunlar)."""
    def status(r: PersonRow) -> str:
        return STATUS_LABELS.get(r.biometrics_status, r.biometrics_status)

    if person_type == "talaba":
        def values(r: PersonRow) -> list:
            course, group = split_course(r.unit)
            return [r.full_name, r.pinfl, r.faculty, course_label(course) if course else "—",
                    group or "—", status(r), r.confirmed_at or "—"]

        return ("Talabalar",
                ["№", "F.I.SH.", "JSHSHIR", "Fakultet", "Kurs", "Guruh", "Yuz holati", "Tasdiqlagan vaqti"],
                [6, 38, 18, 34, 10, 26, 16, 19], values, {1, 3, 5, 7, 8})

    if person_type == "xodim":
        def values(r: PersonRow) -> list:
            return [r.full_name, r.pinfl, r.faculty, r.unit or "—", status(r), r.confirmed_at or "—"]

        return ("Xodimlar",
                ["№", "F.I.SH.", "JSHSHIR", "Fakultet", "Kafedra / Bo'lim", "Yuz holati", "Tasdiqlagan vaqti"],
                [6, 38, 18, 34, 42, 16, 19], values, {1, 3, 6, 7})

    def values(r: PersonRow) -> list:
        return [r.full_name, r.pinfl, "Talaba" if r.type == "talaba" else "Xodim", r.faculty,
                r.unit or "—", status(r), r.confirmed_at or "—"]

    return ("Ro'yxat",
            ["№", "F.I.SH.", "JSHSHIR", "Turi", "Fakultet", "Kurs / Guruh / Bo'lim", "Yuz holati",
             "Tasdiqlagan vaqti"],
            [6, 38, 18, 10, 34, 40, 16, 19], values, {1, 3, 4, 7, 8})


def build_people_workbook(
    rows: list[PersonRow],
    filter_label: str,
    now: datetime,
    person_type: str | None = None,
    title: str = "Talabalar va xodimlar ro'yxati",
) -> bytes:
    """Har bir odam alohida qator — tanlangan filtr bilan AYNAN bir xil."""
    sheet_name, headers, widths, values_of, centered = _people_columns(person_type)
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name

    confirmed = sum(1 for r in rows if r.biometrics_status == "tasdiqlangan")
    _title(
        ws,
        title,
        f"{filter_label}   •   Jami: {len(rows)} ta, shundan yuzi tasdiqlangan: {confirmed} ta, "
        f"tasdiqlanmagan: {len(rows) - confirmed} ta   •   Tuzilgan sana: {_stamp(now)} (Toshkent vaqti)",
        len(headers),
    )

    header_row = 4
    _header(ws, header_row, headers)
    status_col = headers.index("Yuz holati") + 1

    for i, r in enumerate(rows, 1):
        row = header_row + i
        zebra = PatternFill("solid", fgColor=ZEBRA) if i % 2 == 0 else None
        for col, value in enumerate([i, *values_of(r)], 1):
            cell = ws.cell(row=row, column=col, value=value)
            cell.border = _BORDER
            cell.alignment = _CENTER if col in centered else _WRAP
            if zebra is not None:
                cell.fill = zebra

        ws.cell(row=row, column=3).number_format = "@"  # JSHSHIR matn — yuqoridagi izohga qarang

        status_cell = ws.cell(row=row, column=status_col)
        fill = STATUS_FILLS.get(r.biometrics_status)
        if fill:
            status_cell.fill = PatternFill("solid", fgColor=fill)
            status_cell.font = Font(bold=True)

    _widths(ws, widths)
    ws.freeze_panes = ws.cell(row=header_row + 1, column=3)
    if rows:
        ws.auto_filter.ref = f"A{header_row}:{get_column_letter(len(headers))}{header_row + len(rows)}"
    _landscape(ws, header_row)
    return _to_bytes(wb)


# ─────────────────────────────────────────── 2. Statistika

@dataclass
class Bucket:
    confirmed: int = 0
    pending: int = 0
    missing: int = 0

    @property
    def total(self) -> int:
        return self.confirmed + self.pending + self.missing

    def add(self, status: str, count: int) -> None:
        if status == "tasdiqlangan":
            self.confirmed += count
        elif status == "kutilmoqda":
            self.pending += count
        else:
            self.missing += count

    def coverage(self) -> float | None:
        """0..1. None — guruhda odam yo'q ("0%" bilan aralashtirmaslik uchun)."""
        return self.confirmed / self.total if self.total else None


@dataclass
class CoverageData:
    totals: Bucket = field(default_factory=Bucket)
    by_faculty: dict[str, Bucket] = field(default_factory=dict)
    by_unit: dict[tuple[str, str], Bucket] = field(default_factory=dict)
    # Faqat talabalar uchun to'ldiriladi
    by_course: dict[int | None, Bucket] = field(default_factory=dict)
    by_group: dict[tuple[str, int | None, str], Bucket] = field(default_factory=dict)

    def add(self, person_type: str | None, faculty: str, unit: str | None, status: str, count: int) -> None:
        self.totals.add(status, count)
        self.by_faculty.setdefault(faculty, Bucket()).add(status, count)
        if person_type == "talaba":
            course, group = split_course(unit)
            self.by_course.setdefault(course, Bucket()).add(status, count)
            self.by_group.setdefault((faculty, course, group or "—"), Bucket()).add(status, count)
        else:
            self.by_unit.setdefault((faculty, unit or "—"), Bucket()).add(status, count)


def _pct_cell(cell, value: float | None) -> None:
    if value is None:
        cell.value = "—"
        cell.alignment = _CENTER
        return
    cell.value = value
    cell.number_format = "0.0%"
    cell.alignment = _CENTER
    # Qamrov darajasiga qarab fon — qaysi guruh orqada qolgani darhol ko'rinadi
    if value >= 0.8:
        cell.fill = PatternFill("solid", fgColor=STATUS_FILLS["tasdiqlangan"])
    elif value >= 0.4:
        cell.fill = PatternFill("solid", fgColor=STATUS_FILLS["kutilmoqda"])
    else:
        cell.fill = PatternFill("solid", fgColor=STATUS_FILLS["yoq"])


def _bucket_row(ws: Worksheet, row: int, labels: list[str], b: Bucket, *, bold: bool = False,
                zebra: bool = False) -> None:
    values = [*labels, b.total, b.confirmed, b.pending, b.missing]
    fill = PatternFill("solid", fgColor=ZEBRA) if zebra else None
    for col, value in enumerate(values, 1):
        cell = ws.cell(row=row, column=col, value=value)
        cell.border = _BORDER
        cell.alignment = _WRAP if col <= len(labels) else _CENTER
        if bold:
            cell.font = Font(bold=True)
        if fill is not None:
            cell.fill = fill
    pct = ws.cell(row=row, column=len(values) + 1)
    pct.border = _BORDER
    if bold:
        pct.font = Font(bold=True)
    _pct_cell(pct, b.coverage())


_COUNT_HEADERS = ["Jami", "Tasdiqlangan", "Kutilmoqda", "Tasdiqlanmagan", "Qamrov"]


def _table_sheet(wb: Workbook, name: str, title: str, subtitle: str, label_headers: list[str],
                 label_widths: list[float], items: list[tuple[list[str], Bucket]]) -> None:
    ws = wb.create_sheet(name)
    headers = [*label_headers, *_COUNT_HEADERS]
    _title(ws, title, subtitle, len(headers))
    header_row = 4
    _header(ws, header_row, headers)
    for i, (labels, bucket) in enumerate(items, 1):
        _bucket_row(ws, header_row + i, labels, bucket, zebra=i % 2 == 0)
    _widths(ws, [*label_widths, 10, 15, 14, 17, 12])
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    if items:
        ws.auto_filter.ref = f"A{header_row}:{get_column_letter(len(headers))}{header_row + len(items)}"
    _landscape(ws, header_row)


def build_stats_workbook(data: CoverageData, scope_label: str, now: datetime,
                         person_type: str | None = None) -> bytes:
    """Yuzni tasdiqlash qamrovi. Talabalar uchun kurs va guruh kesimi,
    xodimlar (va aralash ro'yxat) uchun kafedra va bo'limlar kesimi."""
    wb = Workbook()
    stamp = f"Tuzilgan sana: {_stamp(now)} (Toshkent vaqti)"

    # ── 1-varaq: umumiy ko'rsatkichlar va fakultetlar
    ws = wb.active
    ws.title = "Umumiy statistika"
    fac_headers = ["Fakultet", *_COUNT_HEADERS]
    _title(ws, "Yuzni tasdiqlash statistikasi", f"{scope_label}   •   {stamp}", len(fac_headers))

    t = data.totals
    summary = [
        ("Jami ro'yxatda", t.total),
        ("Yuzi tasdiqlangan", t.confirmed),
        ("Kutilmoqda", t.pending),
        ("Yuzi tasdiqlanmagan", t.missing),
        ("Qamrov", t.coverage()),
    ]
    start = 4
    for offset, (label, value) in enumerate(summary):
        row = start + offset
        label_cell = ws.cell(row=row, column=1, value=label)
        label_cell.font = Font(bold=True)
        label_cell.border = _BORDER
        label_cell.fill = PatternFill("solid", fgColor=ZEBRA)
        value_cell = ws.cell(row=row, column=2)
        value_cell.border = _BORDER
        value_cell.font = Font(bold=True, size=12)
        if label == "Qamrov":
            _pct_cell(value_cell, value)
        else:
            value_cell.value = value
            value_cell.alignment = _CENTER

    header_row = start + len(summary) + 2
    section = ws.cell(row=header_row - 1, column=1, value="Fakultetlar kesimida")
    section.font = Font(bold=True, size=12, color=NAVY)
    _header(ws, header_row, fac_headers)

    ordered = sorted(data.by_faculty.items(), key=lambda kv: (kv[0] == NO_FACULTY_LABEL, kv[0]))
    row = header_row
    for i, (name, bucket) in enumerate(ordered, 1):
        row = header_row + i
        _bucket_row(ws, row, [name], bucket, zebra=i % 2 == 0)
    _bucket_row(ws, row + 1, ["JAMI"], t, bold=True)

    _widths(ws, [44, 12, 15, 14, 17, 12])
    _landscape(ws, header_row)

    if person_type == "talaba":
        courses = sorted(data.by_course.items(), key=lambda kv: (kv[0] is None, kv[0] or 0))
        _table_sheet(
            wb, "Kurslar", "Kurslar kesimida", f"{scope_label}   •   {stamp}",
            ["Kurs"], [22], [([course_label(course)], bucket) for course, bucket in courses],
        )
        groups = sorted(
            data.by_group.items(),
            key=lambda kv: (kv[0][0] == NO_FACULTY_LABEL, kv[0][0], kv[0][1] is None, kv[0][1] or 0, kv[0][2]),
        )
        _table_sheet(
            wb, "Guruhlar", "Guruhlar kesimida",
            f"{scope_label}   •   Fakultet, kurs va guruh tartibida   •   {stamp}",
            ["Fakultet", "Kurs", "Guruh"], [34, 12, 30],
            [([faculty, course_label(course), group], bucket) for (faculty, course, group), bucket in groups],
        )
    else:
        # Fakultet bo'yicha guruhlab, har guruh ichida qamrovi eng past bo'lgan
        # kafedra yuqorida — "kimga eslatish kerak" degan savolga javob tartibda.
        units = sorted(
            data.by_unit.items(),
            key=lambda kv: (kv[0][0] == NO_FACULTY_LABEL, kv[0][0], kv[1].coverage() or 0.0, kv[0][1]),
        )
        _table_sheet(
            wb, "Kafedra va bo'limlar", "Kafedra va bo'limlar kesimida",
            f"{scope_label}   •   Qamrovi eng past bo'lganlar har fakultet ichida yuqorida   •   {stamp}",
            ["Fakultet", "Kafedra / Bo'lim"], [36, 44],
            [([faculty, unit], bucket) for (faculty, unit), bucket in units],
        )

    return _to_bytes(wb)
