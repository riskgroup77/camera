import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.org import Building


class Camera(Base):
    __tablename__ = "cameras"
    __table_args__ = (CheckConstraint("status IN ('faol', 'nofaol', 'tamirda')", name="ck_cameras_status"),)

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
    # out of specific modules (e.g. no vehicle detection (#25) on an
    # indoor classroom camera). See app/jobs/module_status.py's
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
    # app/jobs/vehicle_ai.py ONLY runs on cameras flagged this way — a
    # vehicle inside a classroom/hallway is nonsensical, so every other
    # camera is excluded outright (not just module-deactivated).
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

    building: Mapped[Building | None] = relationship("Building", lazy="joined")
