"""Jadval bo'yicha kim qayerda — /api/jadval (app/services/schedule_presence.py)."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import CurrentUser, require_permission
from app.schemas.base import CamelModel
from app.services.schedule_presence import board_workbook, day_board
from app.timezone import business_date, local_now
from app.timezone import business_today

router = APIRouter(prefix="/api/jadval", tags=["dars-jadvali"])
ReadDep = Annotated[CurrentUser, Depends(require_permission("manageLessons", "manageAttendance", "viewReports"))]


class BoardRowOut(CamelModel):
    id: str
    start: str | None
    end: str | None
    group: str
    subject: str
    faculty: str
    teacher: str
    teacher_id: str | None
    auditorium: str | None
    building: str | None
    camera_id: str | None
    camera_name: str | None
    # "xonada" | "binoda" | "kelmagan" | None (o'qituvchi bog'lanmagan)
    teacher_status: str | None
    students_expected: int
    students_arrived: int
    students_in_room: int | None


class BoardOut(CamelModel):
    day: str
    now: bool
    items: list[BoardRowOut]


async def _board(db: AsyncSession, day: date, at):
    """day_board — butun kunning darslari, tashriflari va davomati; har bir
    ochiq ekran har daqiqada so'raydi. Daqiqa aniqligida 15 s keshlanadi."""
    from app.services import situation as svc

    minute = at.replace(second=0, microsecond=0) if at is not None else None
    return await svc.cached(("day_board", day, minute), lambda: day_board(db, day, at=minute))


def _day(sana: str | None) -> date:
    if not sana:
        return business_today()
    try:
        return date.fromisoformat(sana)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Sana noto'g'ri (YYYY-MM-DD)") from None


@router.get("/kun", response_model=BoardOut)
async def get_day_board(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: ReadDep,
    sana: Annotated[str | None, Query()] = None,
    hozir: Annotated[bool, Query()] = False,
) -> BoardOut:
    """Kun darslari: kim qayerda bo'lishi kerak va kamera kimni ko'rdi.
    `hozir=true` — faqat hozir davom etayotgan darslar (bugun)."""
    day = _day(sana)
    now = local_now()
    rows = await _board(db, day, now if hozir and day == business_date(now) else None)
    return BoardOut(
        day=day.isoformat(),
        now=hozir,
        items=[
            BoardRowOut(
                **{
                    **row.__dict__,
                    "id": str(row.id),
                    "start": row.start.isoformat() if row.start else None,
                    "end": row.end.isoformat() if row.end else None,
                    "teacher_id": str(row.teacher_id) if row.teacher_id else None,
                    "camera_id": str(row.camera_id) if row.camera_id else None,
                }
            )
            for row in rows
        ],
    )


@router.get("/kun.xlsx")
async def export_day_board(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: ReadDep,
    sana: Annotated[str | None, Query()] = None,
    hozir: Annotated[bool, Query()] = False,
) -> Response:
    day = _day(sana)
    now = local_now()
    data = board_workbook(day, await _board(db, day, now if hozir and day == business_date(now) else None))
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="jadval-davomat-{day.isoformat()}.xlsx"'},
    )


@router.get("/kun.pdf")
async def export_day_board_pdf(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: ReadDep,
    sana: Annotated[str | None, Query()] = None,
    hozir: Annotated[bool, Query()] = False,
) -> Response:
    """Kim qayerda — darslar jadvali PDF (hozir=true: faqat hozirgi darslar)."""
    from app.services import pdf_export
    from app.timezone import to_local

    day = _day(sana)
    now = local_now()
    rows = await _board(db, day, now if hozir and day == business_date(now) else None)
    labels = {"xonada": "Xonada", "binoda": "Binoda", "kelmagan": "Kamera ko'rmadi"}

    def hm(moment):
        return to_local(moment).strftime("%H:%M") if moment else "—"

    table = [
        [f"{hm(r.start)}–{hm(r.end)}", r.group, r.subject, ", ".join(p for p in (r.auditorium, r.building) if p) or "—",
         r.teacher, labels.get(r.teacher_status or "", "bazada topilmadi"),
         f"{r.students_arrived}/{r.students_expected}", "—" if r.students_in_room is None else r.students_in_room]
        for r in rows
    ]
    tones = {i: "danger" for i, r in enumerate(rows) if r.teacher_status == "kelmagan"}
    document = pdf_export.PdfDocument(
        title="Kim qayerda — dars jadvali bo'yicha",
        columns=[
            pdf_export.PdfColumn("Vaqt", 1), pdf_export.PdfColumn("Guruh", 1), pdf_export.PdfColumn("Fan", 2.2),
            pdf_export.PdfColumn("Xona", 1.8), pdf_export.PdfColumn("O'qituvchi", 2), pdf_export.PdfColumn("O'qituvchi holati", 1.3),
            pdf_export.PdfColumn("Talabalar keldi", 1, "CENTER"), pdf_export.PdfColumn("Xonada", 0.8, "CENTER"),
        ],
        rows=table, row_tones=tones,
        filters=[("Sana", day.isoformat())] + ([("Ko'rinish", "faqat hozirgi darslar")] if hozir else []),
        counts=[("Darslar", len(rows)), ("O'qituvchini kamera ko'rmadi", sum(1 for r in rows if r.teacher_status == "kelmagan")),
                ("Talabalar keldi", f"{sum(r.students_arrived for r in rows)}/{sum(r.students_expected for r in rows)}")],
    )
    return Response(
        content=await pdf_export.render_async(document), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="jadval-davomat-{day.isoformat()}.pdf"'},
    )
