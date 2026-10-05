import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, SmallInteger, String, event, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, attributes, mapped_column, relationship

from app.database import Base
from app.models.org import Building


class Camera(Base):
    __tablename__ = "cameras"
    __table_args__ = (
        CheckConstraint("status IN ('faol', 'nofaol', 'tamirda')", name="ck_cameras_status"),
        CheckConstraint(
            "face_direction IS NULL OR face_direction IN ('kirish', 'chiqish')",
            name="ck_cameras_face_direction",
        ),
        CheckConstraint(
            "room_type IS NULL OR room_type IN "
            "('kirish', 'auditoriya', 'laboratoriya', 'koridor', 'ofis', 'cheklangan', 'tashqi')",
            name="ck_cameras_room_type",
        ),
        CheckConstraint(
            "ptz_protocol IS NULL OR ptz_protocol IN ('onvif', 'isapi')",
            name="ck_cameras_ptz_protocol",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    name: Mapped[str] = mapped_column(String, nullable=False)
    ip: Mapped[str] = mapped_column(String, nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=554)
    rtsp_path: Mapped[str | None] = mapped_column(String, nullable=True)
    # Fernet bilan shifrlangan holda saqlanadi (app/crypto.py) — bu ustunlarga
    # to'g'ridan-to'g'ri emas, faqat encrypt()/decrypt() orqali murojaat qiling.
    # Parol kabi bir tomonlama xeshlash bu yerda ishlamaydi, chunki RTSP
    # handshake uchun qiymat qayta o'qilishi (decrypt qilinishi) shart.
    rtsp_username: Mapped[str | None] = mapped_column(String, nullable=True)
    rtsp_password: Mapped[str | None] = mapped_column(String, nullable=True)

    building_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("buildings.id", ondelete="SET NULL"), nullable=True, index=True
    )
    zone: Mapped[str] = mapped_column(String, nullable=False)

    # Qavat raqami — Video Monitoring Markazi kampusni bino -> qavat ->
    # kamera bo'lib ochadi (app/routers/public.py get_campus), shunda bir
    # sahifaga 100+ kamera emas, faqat tanlangan qavat yuklanadi.
    #
    # Nullable ataylab: zona matni ('3-qavat koridor') bu ma'lumotni
    # ishonchli bermaydi va hamma kamerada ham yo'q. Qavati
    # belgilanmagan kamera kesimda 'Qavat belgilanmagan' guruhida
    # ko'rinadi — ya'ni yo'qolmaydi, aksincha belgilash kerakligi
    # ko'zga tashlanadi.
    floor: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    # Kafedra — binodan mustaqil saqlanadi (Department izohiga qarang).
    # Nullable: mavjud 107 kameraning hech biriga kafedra biriktirilmagan
    # va biriktirilmaguncha ular bino bo'yicha filtrlanaveradi.
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Populated by app/services/camera_import.py (SADP/onvif-style discovery
    # export) — stable across DHCP/manual IP reassignment, so re-running an
    # import dedupes by this instead of by `ip`. Null for cameras added by
    # hand, since the admin UI has no reason to ask for it.
    mac_address: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    resolution: Mapped[str] = mapped_column(String, nullable=False)
    fps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="nofaol")
    stream_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # Set only by app/jobs/camera_health.py's periodic TCP reachability sweep
    # — deliberately separate from `status` above. `status` is the admin's
    # *intent* ("this camera should be active"); `last_seen_at` is what was
    # actually, recently observed. Without this split, a camera whose cable
    # gets unplugged silently keeps showing "faol"/live everywhere (Monitoring
    # page, admin table) until someone happens to click "Ulanishni tekshirish"
    # — the exact gap this column closes.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Oxirgi marta bu kameradan YAROQLI kadr olingan vaqt.
    #
    # last_seen_at dan farqi muhim: u kamera RTSP portiga javob
    # berayotganini bildiradi, bu esa tasvir kelayotganini. Ikkalasi bir
    # narsa emas — audit paytida 107 kameradan 6 tasi "JONLI" ko'rinib
    # turgan holda faqat bo'sh kulrang kadr berayotgani aniqlandi:
    # port ochiq, dekoder esa hech narsa chiqarmaydi.
    last_frame_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # TT kriteriya 2 ("Taqiqlangan zonaga kirish") — app/jobs/zone_entry_ai.py.
    # A list of [x, y] pairs, each normalized 0-1 of the frame's width/height
    # (same convention as app/services/pose_detection.py's landmark
    # coordinates, so no separate coordinate-system conversion is needed
    # when checking a detected person's position against this polygon).
    # Nullable/no admin UI to draw one yet — a camera without this set is
    # simply invisible to zone_entry_ai.py, same "not configured yet"
    # pattern as stream_url being unset for the other AI sweep loops.
    restricted_zone_polygon: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # Kamera↔AI-modul bog'lanishi — a list of AIModuleConfig.code integers
    # this camera is EXCLUDED from (not an allow-list). Exclusion, not
    # inclusion, so every existing camera (this column is nullable, no
    # migration backfill needed) keeps its current behavior — every active
    # module still runs on it — until an admin deliberately opts a camera
    # out of specific modules (e.g. no white-coat check (#10) on an
    # administrative-corridor camera). See app/jobs/module_status.py's
    # camera_allows_module() for the query-side filter every sweep loop
    # applies alongside AIModuleConfig.active.
    excluded_module_codes: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # TT kriteriya 3/6/7/8 (davomat) — app/jobs/attendance_ai.py grabs a
    # multi-frame BURST (not one frame) from a camera flagged this way,
    # since an entrance/corridor camera is exactly where someone passing
    # through briefly (turned away in one frame, visible in the next) is
    # most likely to get missed by a single-frame sample. False by
    # default — an admin marks specific cameras as entrances; every other
    # camera keeps today's single-frame behavior (burst-grabbing every
    # camera would just add ffmpeg/inference load with no benefit for a
    # camera where people linger, e.g. a classroom).
    is_entrance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Hovli, bino oldi, avtoturargoh. is_entrance (piyoda kirish) bilan
    # birga yoki alohida belgilanadi.
    #
    # 2026-09-07 gacha app/jobs/vehicle_ai.py (#25 "Hovlida transport
    # harakati") FAQAT shu bayroqli kameralarda ishlardi. O'sha kriteriya
    # olib tashlangandan keyin bayroq hech qanday sweepni cheklamaydi —
    # u ustunda qoldirildi, chunki kameraning qayerda turgani (hovli,
    # bino oldi, avtoturargoh) inventarizatsiya ma'lumoti sifatida
    # qimmatli va admin uni allaqachon to'ldirgan.
    #
    # Deliberately NOT used to restrict TT kriteriya 1 (begona shaxs/
    # unauthorized-person) coverage, despite this field's name: an
    # unrecognized face is worth flagging anywhere in the building, not
    # only at the perimeter — narrowing that module's coverage would be a
    # real security regression, not a cleanup. See app/jobs/
    # unified_face_sweep.py's needs_unauthorized for the actual (deliberately
    # building-wide) gate.
    is_perimeter: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # TT kriteriya 6/7 (davomat) — app/jobs/attendance_ai.py only ever
    # advances AttendanceRecord.check_out from a sighting on a camera
    # flagged this way. Without this, "check_out" was really just "last
    # seen by ANY camera today" — being spotted once by an ordinary
    # interior camera (a classroom, a hallway) doesn't mean someone left
    # the building, but it was silently treated as if it did. False by
    # default — an admin marks the actual exit/main-gate camera(s); every
    # other camera's sighting still confirms the person is present today
    # (keldi/kech_keldi) but never touches check_out.
    is_exit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Xona turi: qaysi AI modullari shu kamerada ishlashini belgilaydi —
    # app/services/camera_roles.py (MODULE_ROOM_TYPES). NULL — belgilanmagan:
    # tur eski bayroqlardan olinadi (kirish/perimetr), aks holda kamera faqat
    # xavfsizlik mezonlarida (yong'in, jang, tartib, zona) qatnashadi.
    room_type: Mapped[str | None] = mapped_column(String, nullable=True)
    # Dars jadvalidagi xona raqami, normallashtirilgan ko'rinishda
    # (camera_roles.normalize_room_code: "211-xona" -> "211"). Jadval importi
    # darsni shu raqam orqali kameraga bog'laydi (app/services/lesson_import.py).
    room_code: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    # Eshik hududi — kirish kamerasida yuz faqat shu yerda qidiriladi, kadrning
    # qolgan qismi tahlil qilinmaydi (app/services/camera_roles.face_roi_box).
    # restricted_zone_polygon bilan bir xil format: normallashgan [x, y] juftliklari.
    # 4K kadrda eshik atrofi to'liq sifatda olinadi: detektorga yuz 3-6 barobar
    # katta ko'rinadi, hisob esa bir necha barobar kam.
    face_roi: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Kirish kamerasida yuzi ko'rinayotgan odam qaysi tomonga ketyapti:
    # "kirish" — kamera binoga kirayotganlarning yuzini ko'radi (ichkaridan
    # eshikka qaragan), "chiqish" — chiqayotganlarnikini. NULL — noma'lum
    # (kamera ikkala tomonni ham ko'radi). app/jobs/attendance_ai.py kelish va
    # ketishni shu bo'yicha ajratadi.
    face_direction: Mapped[str | None] = mapped_column(String, nullable=True)

    # PTZ boshqaruvi (app/services/ptz.py). ptz_protocol: 'onvif' yoki
    # 'isapi' (Hikvision). onvif_port NULL — 80. Login/parol RTSP bilan bir xil.
    ptz_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    ptz_protocol: Mapped[str | None] = mapped_column(String, nullable=True)
    onvif_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Qavat rejasidagi joyi (app/models/platform.py FloorPlan): nisbiy
    # koordinatalar 0..1, burchak — kamera qaragan yo'nalish (gradus).
    plan_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    plan_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    plan_rotation: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    # Ko'rish burchagi (gradus) — xaritada konus kengligi. Obyektivga
    # bog'liq, joyga emas: kamera boshqa qavatga ko'chsa ham saqlanadi.
    plan_fov: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=70, server_default="70")
    # Kunlik video tahlil: kameraning yozuvi qaysi NVR'ning qaysi kanalida
    # (app/services/nvr/). NULL — yozuv olinmaydi, kamera tahlil qilinmaydi.
    nvr_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("nvr_devices.id", ondelete="SET NULL"), nullable=True, index=True
    )
    nvr_channel: Mapped[int | None] = mapped_column(Integer, nullable=True)

    building: Mapped[Building | None] = relationship("Building", lazy="joined")
    department: Mapped["Department | None"] = relationship("Department", lazy="joined")


def _reset_plan_position(target: Camera, value, oldvalue, _initiator) -> None:
    """Kamera boshqa bino yoki qavatga ko'chirilsa, eski qavat rejasidagi
    joyi yangi qavat rejasida noto'g'ri nuqtada ko'rinib qolmasin.
    Qiymat yuklanmagan (oldvalue noma'lum) bo'lsa tegilmaydi."""
    if oldvalue in (attributes.NO_VALUE, attributes.NEVER_SET) or value == oldvalue:
        return
    target.plan_x = None
    target.plan_y = None
    target.plan_rotation = None


event.listen(Camera.building_id, "set", _reset_plan_position)
event.listen(Camera.floor, "set", _reset_plan_position)
