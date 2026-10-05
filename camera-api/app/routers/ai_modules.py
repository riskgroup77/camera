"""AI modules REGISTRY endpoints.

Manages which of the TT hujjat's 25 criteria are enabled and their tuning
knobs (threshold, sensitivity, mode). Most criteria DO have a real
detector behind them (classical CV/heuristics in app/jobs/*.py — see each
row's `method` field and app/seed.py's per-criterion notes), enforced by
every sweep loop via app/jobs/module_status.py; `accuracy` is frequently 0
not because nothing runs, but because nobody has benchmarked that
heuristic against ground truth yet.

Rejim (2026-09): kalibrlanmagan detektorlar `sinov` rejimida ishlaydi —
signal yoziladi, lekin operator navbatiga chiqmaydi. Aniqlik tasodifiy
namunani baholash orqali o'lchanadi (GET /{code}/trial-sample) va
yetarli bo'lgachgina modul `ishchi` rejimga o'tkaziladi.
"""

import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import false, func, select, true, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_action
from app.database import get_db
from app.services.access_scope import event_filter
from app.dependencies import CurrentUser, require_permission
from app.models import AIModuleConfig, Camera, Event, ModuleCameraSuppression, User
from app.schemas.ai_module import AIModuleOut, AIModuleUpdateIn, ModuleSopIn, ModuleSopOut, ModuleSuppressionOut
from app.schemas.event import EventOut
from app.services.camera_module_mapping import camera_counts_by_module
from app.services.event_bus import event_to_out
from app.services.sop import default_steps, parse_steps, resolve_steps
from app.timezone import to_local

router = APIRouter(prefix="/api/ai-modules", tags=["ai-modules"])

PermDep = Annotated[CurrentUser, Depends(require_permission("configureAi"))]
# Sinov namunasini Hodisalar sahifasidagi operator ham baholaydi.
# Ro'yxatni o'qish: bildirishnoma qoidalari ham modul nomlari va ro'yxatini
# ko'rsatadi (NotificationsPage) — faqat configureAi bilan u bo'sh qolardi.
ListDep = Annotated[CurrentUser, Depends(require_permission("configureAi", "manageNotifications"))]
TrialSampleDep = Annotated[CurrentUser, Depends(require_permission("reviewEvents", "configureAi"))]

# Hodisa bermaydigan, davomat yozadigan mezonlar.
ATTENDANCE_MODULE_CODES = {6, 7, 8, 9}
PRECISION_WINDOW_DAYS = 90
MIN_REVIEWS_FOR_PRECISION = 10
# Sinovdan ishchi rejimga o'tish sharti.
STABLE_MIN_REVIEWS = 30
PROMOTION_MIN_PRECISION = 80.0
TRIAL_SAMPLE_DAYS = 14
TRIAL_SAMPLE_MAX = 50


async def _review_stats(db: AsyncSession) -> dict[int, tuple[int, int, int, int]]:
    """module_code -> (tasdiqlangan, rad_etilgan, jami, baholanmagan sinov) oxirgi 90 kun.

    Sinov signallari ham hisoblanadi: sinovdagi modulning aniqligi aynan
    ular bo'yicha o'lchanadi."""
    since = datetime.now(timezone.utc) - timedelta(days=PRECISION_WINDOW_DAYS)
    rows = (
        await db.execute(
            select(Event.module_code, Event.status, Event.is_trial, func.count())
            .where(Event.occurred_at >= since)
            .group_by(Event.module_code, Event.status, Event.is_trial)
        )
    ).all()
    acc: dict[int, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    for code, status_value, is_trial, count in rows:
        # hal_qilindi — signal haqiqiy bo'lib chiqqan va yopilgan.
        if status_value in ("tasdiqlangan", "hal_qilindi"):
            acc[code][0] += count
        elif status_value == "rad_etilgan":
            acc[code][1] += count
        elif is_trial:
            acc[code][3] += count
        acc[code][2] += count
    return {code: (c, r, t, pending) for code, (c, r, t, pending) in acc.items()}


def _promotion_ready(confirmed: int, rejected: int) -> bool:
    reviewed = confirmed + rejected
    return reviewed >= STABLE_MIN_REVIEWS and confirmed * 100 / reviewed >= PROMOTION_MIN_PRECISION


def _maturity(module: AIModuleConfig, confirmed: int, rejected: int) -> tuple[str, float | None, str]:
    reviewed = confirmed + rejected
    precision = round(confirmed / reviewed * 100, 1) if reviewed >= MIN_REVIEWS_FOR_PRECISION else None
    if precision is not None and precision < 50:
        return (
            "sozlash_kerak",
            precision,
            f"Ko'rib chiqilgan {reviewed} signalning {round(100 - precision)}% i yolg'on — "
            "chegarani oshiring yoki kameralarni tekshiring",
        )
    if module.code in ATTENDANCE_MODULE_CODES:
        return "asosiy", precision, "Hodisa bermaydi — natijasi davomat va \"Davomat kameralari\" tashxisida ko'rinadi"
    if module.mode == "sinov":
        if _promotion_ready(confirmed, rejected):
            return (
                "sinov",
                precision,
                f"Sinov natijasi yaxshi: {reviewed} ta baholangan signal, aniqlik {precision}% — "
                "ishchi rejimga o'tkazish mumkin",
            )
        progress = f"hozir {reviewed} ta" + (f", aniqlik {precision}%" if precision is not None else "")
        return (
            "sinov",
            precision,
            "Sinov rejimi: signallar operator navbatiga chiqmaydi, tasodifiy namunalar baholanadi. "
            f"Ishchi rejim uchun kamida {STABLE_MIN_REVIEWS} ta baholangan signal va "
            f"{int(PROMOTION_MIN_PRECISION)}% aniqlik kerak ({progress})",
        )
    if precision is None:
        return (
            "asosiy",
            None,
            f"Aniqlik hali o'lchanmagan: kamida {MIN_REVIEWS_FOR_PRECISION} ta signal ko'rib chiqilishi kerak (hozir {reviewed})",
        )
    return "asosiy", precision, f"{reviewed} ta ko'rib chiqilgan signal asosida"


def _to_out(module: AIModuleConfig, camera_count: int, stats: tuple[int, int, int, int] = (0, 0, 0, 0)) -> AIModuleOut:
    confirmed, rejected, total, trial_unreviewed = stats
    maturity, precision, note = _maturity(module, confirmed, rejected)
    return AIModuleOut(
        id=str(module.id),
        code=module.code,
        group=module.group,
        name=module.name,
        description=module.description,
        method=module.method,
        # Qo'lda yozilgan statik foiz emas — o'lchangan aniqlik (bo'lmasa 0).
        accuracy=precision if precision is not None else 0,
        threshold=module.threshold,
        sensitivity=module.sensitivity,
        camera_count=camera_count,
        active=module.active,
        has_detector=module.has_detector,
        measured_precision=precision,
        reviewed_events=confirmed + rejected,
        recent_events=total,
        maturity=maturity,
        maturity_note=note,
        mode=module.mode,
        promotion_ready=module.mode == "sinov" and _promotion_ready(confirmed, rejected),
        trial_unreviewed=trial_unreviewed,
    )


@router.get("", response_model=list[AIModuleOut])
async def list_ai_modules(db: Annotated[AsyncSession, Depends(get_db)], _: ListDep) -> list[AIModuleOut]:
    modules = (await db.execute(select(AIModuleConfig).order_by(AIModuleConfig.code))).scalars().all()
    stats = await _review_stats(db)
    counts = await camera_counts_by_module(db)
    return [_to_out(m, counts.get(m.code, 0), stats.get(m.code, (0, 0, 0, 0))) for m in modules]


@router.get("/suppressions", response_model=list[ModuleSuppressionOut])
async def list_suppressions(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: PermDep,
) -> list[ModuleSuppressionOut]:
    """Operatorlar ko'p rad etgani uchun avtomatik o'chirilgan kamera × modul juftliklari."""
    rows = (
        await db.execute(
            select(ModuleCameraSuppression, Camera)
            .join(Camera, Camera.id == ModuleCameraSuppression.camera_id)
            .where(ModuleCameraSuppression.restored_at.is_(None))
            .order_by(ModuleCameraSuppression.created_at.desc())
        )
    ).all()
    names = dict((await db.execute(select(AIModuleConfig.code, AIModuleConfig.name))).all())
    return [
        ModuleSuppressionOut(
            id=str(suppression.id),
            camera_id=str(camera.id),
            camera_name=camera.name,
            building=camera.building.name if camera.building else "",
            module_code=suppression.module_code,
            module_name=names.get(suppression.module_code, f"#{suppression.module_code}"),
            confirmed=suppression.confirmed,
            rejected=suppression.rejected,
            precision=suppression.precision,
            reason=suppression.reason,
            created_at=to_local(suppression.created_at).strftime("%Y-%m-%d %H:%M"),
        )
        for suppression, camera in rows
    ]


@router.post("/suppressions/{suppression_id}/restore", status_code=status.HTTP_204_NO_CONTENT)
async def restore_suppression(
    suppression_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: PermDep,
) -> None:
    try:
        suppression_uuid = uuid.UUID(suppression_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Yozuv topilmadi") from None
    suppression = await db.get(ModuleCameraSuppression, suppression_uuid)
    if suppression is None or suppression.restored_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Yozuv topilmadi yoki allaqachon qaytarilgan")

    user = await db.get(User, current_user.id)
    camera = await db.get(Camera, suppression.camera_id)
    suppression.restored_at = datetime.now(timezone.utc)
    suppression.restored_by = user.full_name if user else None
    await log_action(
        db,
        request,
        current_user.id,
        f"Avtomatik o'chirilgan modulni qaytardi: #{suppression.module_code} — {camera.name if camera else suppression.camera_id}",
        "AI Modullari",
    )
    await db.commit()


@router.get("/{code}/trial-sample", response_model=list[EventOut])
async def trial_sample(
    code: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TrialSampleDep,
    limit: Annotated[int, Query(ge=1, le=TRIAL_SAMPLE_MAX)] = 12,
) -> list[EventOut]:
    """Sinov signallaridan TASODIFIY, hali baholanmagan namuna.

    Aniqlik xolis bo'lishi uchun: operator faqat "qiziq" ko'ringan
    signallarni emas, tasodifan tanlanganlarini baholaydi."""
    since = datetime.now(timezone.utc) - timedelta(days=TRIAL_SAMPLE_DAYS)
    rows = (
        await db.execute(
            select(Event)
            .where(Event.module_code == code)
            .where(Event.is_trial == true())
            .where(Event.status == "yangi")
            .where(Event.occurred_at >= since)
            .where(event_filter(current_user))
            .order_by(func.random())
            .limit(limit)
        )
    ).scalars().all()
    return [event_to_out(event) for event in rows]


@router.patch("/{module_id}", response_model=AIModuleOut)
async def update_ai_module(
    module_id: str,
    body: AIModuleUpdateIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: PermDep,
) -> AIModuleOut:
    result = await db.execute(select(AIModuleConfig).where(AIModuleConfig.id == module_id))
    module = result.scalar_one_or_none()
    if module is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Modul topilmadi")

    if body.active and not module.has_detector:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Bu modul uchun hali aniqlash logikasi yozilmagan — faollashtirib bo'lmaydi",
        )

    stats = await _review_stats(db)
    action = f"AI modulni sozladi: {module.name}"
    if body.mode is not None and body.mode != module.mode:
        if body.mode == "ishchi":
            confirmed, rejected, _total, _pending = stats.get(module.code, (0, 0, 0, 0))
            if not _promotion_ready(confirmed, rejected):
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"Ishchi rejimga o'tkazish uchun kamida {STABLE_MIN_REVIEWS} ta baholangan sinov signali va "
                    f"{int(PROMOTION_MIN_PRECISION)}% aniqlik kerak (hozir {confirmed + rejected} ta)",
                )
        module.mode = body.mode
        action = f"AI modul rejimini o'zgartirdi: {module.name} — {'ishchi' if body.mode == 'ishchi' else 'sinov'}"
        if body.mode == "sinov":
            # Navbatda kutayotgan (hali ko'rilmagan) signallar ham sinovga o'tadi —
            # aks holda operator navbati shu modulning eski shovqini bilan to'la qolardi.
            moved = await db.execute(
                update(Event)
                .where(Event.module_code == module.code)
                .where(Event.status == "yangi")
                .where(Event.is_trial == false())
                .values(is_trial=True)
            )
            if moved.rowcount:
                action += f" ({moved.rowcount} ta ko'rilmagan signal sinov namunalariga o'tkazildi)"

    module.threshold = body.threshold
    module.sensitivity = body.sensitivity
    module.active = body.active

    await log_action(db, request, current_user.id, action, "AI Modullari")
    await db.commit()
    await db.refresh(module)
    counts = await camera_counts_by_module(db)
    return _to_out(module, counts.get(module.code, 0), stats.get(module.code, (0, 0, 0, 0)))


# ---------------------------------------------------------------------------
# Operator ko'rsatmasi (SOP) — app/services/sop.py
# ---------------------------------------------------------------------------


async def _module_by_code(db: AsyncSession, code: int) -> AIModuleConfig:
    module = (await db.execute(select(AIModuleConfig).where(AIModuleConfig.code == code))).scalar_one_or_none()
    if module is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Modul topilmadi")
    return module


def _sop_out(module: AIModuleConfig) -> ModuleSopOut:
    return ModuleSopOut(
        code=module.code,
        name=module.name,
        steps=resolve_steps(module.code, module.sop),
        custom=bool(parse_steps(module.sop)),
        default_steps=default_steps(module.code),
    )


@router.get("/{code}/sop", response_model=ModuleSopOut)
async def get_module_sop(code: int, db: Annotated[AsyncSession, Depends(get_db)], _: TrialSampleDep) -> ModuleSopOut:
    return _sop_out(await _module_by_code(db, code))


@router.put("/{code}/sop", response_model=ModuleSopOut)
async def update_module_sop(
    code: int,
    body: ModuleSopIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: PermDep,
) -> ModuleSopOut:
    """Ko'rsatmani o'zgartirish. Bo'sh ro'yxat — standartga qaytarish
    (ustun NULL bo'ladi va keyingi standart yaxshilanishlari ham tarqaladi)."""
    module = await _module_by_code(db, code)
    steps = parse_steps("\n".join(body.steps or []))
    module.sop = "\n".join(steps) if steps else None
    action = (
        f"Hodisa ko'rsatmasini o'zgartirdi: {module.name} ({len(steps)} qadam)"
        if steps
        else f"Hodisa ko'rsatmasini standartga qaytardi: {module.name}"
    )
    await log_action(db, request, current_user.id, action, "AI Modullari")
    await db.commit()
    return _sop_out(module)
