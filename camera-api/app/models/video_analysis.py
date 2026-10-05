"""Kunlik video tahlil jadvallari — docs/KUNLIK_VIDEO_TAHLIL.md.

  * NvrDevice            — yozuvlar olinadigan NVR (yoki eksport papkasi);
  * VideoAnalysisRun     — bitta kunning tahlili (holat va statistika);
  * VideoAnalysisJob     — bitta kamera × vaqt oralig'i (qayta urinish birligi);
  * VideoObservation     — videoda tanilgan bitta yuz (agregatsiya xom ashyosi);
  * DailyPersonCriteria  — har odam × kun: barcha kriteriyalar natijasi.
"""

import uuid
from datetime import date as date_type, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import false, func, true

from app.database import Base

NVR_KINDS = ("hikvision", "fayl")
RUN_STATUSES = ("navbatda", "ishlamoqda", "agregatsiya", "tugadi", "xato", "bekor")
JOB_STATUSES = ("navbatda", "ishlamoqda", "tugadi", "xato", "yozuv_yoq", "bekor")


class NvrDevice(Base):
    """Video yozuvlari manbai.

    `hikvision` — tarmoqdagi NVR: kanal ro'yxati va yozuv qidiruvi ISAPI
    orqali (HTTP, Digest), video RTSP playback yoki ISAPI download orqali.
    `fayl` — NVR'dan eksport qilingan yozuvlar papkasi:
    `<base_path>/<kanal>/<YYYYMMDD>_<HHMMSS>.<kengaytma>` (sinov va zaxira
    yo'l: NVR tarmoqda bo'lmasa, yozuvni USB orqali olib kelish mumkin)."""

    __tablename__ = "nvr_devices"
    __table_args__ = (
        CheckConstraint("kind IN ('hikvision', 'fayl')", name="ck_nvr_devices_kind"),
        CheckConstraint("stream IN ('main', 'sub')", name="ck_nvr_devices_stream"),
        CheckConstraint("fetch_mode IN ('rtsp', 'download')", name="ck_nvr_devices_fetch_mode"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False, default="hikvision", server_default="hikvision")
    ip: Mapped[str | None] = mapped_column(String, nullable=True)
    http_port: Mapped[int] = mapped_column(Integer, nullable=False, default=80, server_default="80")
    rtsp_port: Mapped[int] = mapped_column(Integer, nullable=False, default=554, server_default="554")
    username: Mapped[str | None] = mapped_column(String, nullable=True)
    # app/crypto.py bilan shifrlangan (kamera paroli kabi).
    password: Mapped[str | None] = mapped_column(String, nullable=True)
    # Qaysi oqim yozuvi o'qiladi: asosiy (aniqroq yuz) yoki sub (yengilroq).
    stream: Mapped[str] = mapped_column(String, nullable=False, default="main", server_default="main")
    # "download" — ISAPI orqali fayl sifatida (real vaqtdan bir necha marta
    # tez); "rtsp" — playback oqimi (real vaqt tezligida, lekin hamma NVR'da
    # bor). Download yiqilsa vazifa avtomatik RTSP bilan qayta o'qiladi.
    fetch_mode: Mapped[str] = mapped_column(String, nullable=False, default="download", server_default="download")
    # NVR bir vaqtda beradigan playback oqimlari chegarasi.
    max_streams: Mapped[int] = mapped_column(Integer, nullable=False, default=8, server_default="8")
    # Hikvision playback URL'idagi vaqt NVR'ning mahalliy soatida (oxirida
    # "Z" bo'lsa ham) — ko'p modellarda shunday. Aksi bo'lsa false.
    local_time: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    # RTSP playback yo'li shabloni: {channel} {stream} (1 — asosiy, 2 — sub),
    # {start} {end} (YYYYMMDDTHHMMSSZ).
    rtsp_path_template: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="/Streaming/tracks/{channel}0{stream}?starttime={start}&endtime={end}",
        server_default="/Streaming/tracks/{channel}0{stream}?starttime={start}&endtime={end}",
    )
    base_path: Mapped[str | None] = mapped_column(String, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VideoAnalysisRun(Base):
    __tablename__ = "video_analysis_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('navbatda', 'ishlamoqda', 'agregatsiya', 'tugadi', 'xato', 'bekor')",
            name="ck_video_analysis_runs_status",
        ),
        Index("ix_video_analysis_runs_day", "day"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    day: Mapped[date_type] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="navbatda")
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    jobs_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_no_video: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    frames_planned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    frames_analyzed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    faces_detected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    observations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Kriteriyalar bo'yicha yakuniy sonlar (agregatsiyadan keyin).
    stats: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[str] = mapped_column(String, nullable=False, default="tizim")
    # Qo'lda bekor qilish so'rovi — ishlayotgan vazifalar keyingi kadrda to'xtaydi.
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


class VideoAnalysisJob(Base):
    __tablename__ = "video_analysis_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('navbatda', 'ishlamoqda', 'tugadi', 'xato', 'yozuv_yoq', 'bekor')",
            name="ck_video_analysis_jobs_status",
        ),
        Index("ix_video_analysis_jobs_run_status", "run_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("video_analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    camera_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True
    )
    lesson_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lesson_sessions.id", ondelete="SET NULL"), nullable=True
    )
    # kirish | dars | umumiy | chekish
    kind: Mapped[str] = mapped_column(String, nullable=False)
    # Bitta vazifa bir nechta klipdan iborat bo'lishi mumkin (dars: har
    # daqiqada 3 s) — [[boshlanish_iso, tugash_iso, fps, [maqsadlar]], ...].
    clips: Mapped[list] = mapped_column(JSONB, nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    frames_planned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String, nullable=False, default="navbatda")
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    frames: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    faces: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    observations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Qaysi kliplarda video haqiqatan o'qildi — qamrov (agregatsiya
    # "kelmadi"/"erta ketdi" deyishdan oldin shuni tekshiradi).
    covered: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Vazifaning tahlil natijalari (poza, chekish va h.k.) — agregatsiya uchun.
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VideoObservation(Base):
    """Videoda tanilgan bitta yuz (bir klipdagi kuzatuv — track — bitta qator).

    Notanish yuzlar yozilmaydi: kriteriyalar har biri ma'lum odam haqida."""

    __tablename__ = "video_observations"
    __table_args__ = (
        Index("ix_video_observations_day_person", "day", "student_staff_id"),
        Index("ix_video_observations_job", "job_id"),
        Index("ix_video_observations_run", "run_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("video_analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("video_analysis_jobs.id", ondelete="CASCADE"), nullable=False
    )
    day: Mapped[date_type] = mapped_column(Date, nullable=False)
    camera_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True
    )
    student_staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students_staff.id", ondelete="CASCADE"), nullable=False
    )
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    similarity: Mapped[float] = mapped_column(Float, nullable=False)
    margin: Mapped[float] = mapped_column(Float, nullable=False)
    frames: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    face_px: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    # Diqqat (#19) namunalari: yuz kameraga qaragan / telefon yonida (kadrlar soni).
    frontal_frames: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    phone_frames: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    # Xalat (#10): baholangan kadrlar va ulardan oq deb topilganlari.
    coat_frames: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    coat_white_frames: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    coat_fraction: Mapped[float | None] = mapped_column(Float, nullable=True)
    # O'qituvchi faolligi (#21): tana harakati (0-100), o'lchangan bo'lsa.
    movement: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Vazifadagi klip raqami (dars bosqichini aniqlash uchun — VideoAnalysisJob.clips).
    clip_index: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    # Xalat dalili (kesilgan rasm, MinIO) — kun bo'yi bitta odamga bittagacha.
    evidence_key: Mapped[str | None] = mapped_column(String, nullable=True)


class DailyPersonCriteria(Base):
    """Har odam × kun — barcha kriteriyalar bitta qatorda.

    Qiymat NULL — o'lchanmadi (kamera ko'rmadi yoki talab qilinmaydi);
    0 yoki "yo'q" bilan adashtirilmasin."""

    __tablename__ = "daily_person_criteria"
    __table_args__ = (
        UniqueConstraint("student_staff_id", "day", name="uq_daily_person_criteria"),
        Index("ix_daily_person_criteria_day", "day"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    student_staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students_staff.id", ondelete="CASCADE"), nullable=False
    )
    day: Mapped[date_type] = mapped_column(Date, nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("video_analysis_runs.id", ondelete="SET NULL"), nullable=True
    )
    # #6/#7 kunlik davomat
    attendance_status: Mapped[str | None] = mapped_column(String, nullable=True)
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    late_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # #9 ishdan erta ketish: erta_ketdi | vaqtida | aniqlanmadi | tegishli_emas
    early_leave: Mapped[str | None] = mapped_column(String, nullable=True)
    sightings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cameras_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # #7/#8/#9 dars bo'yicha (talaba)
    lessons_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lessons_attended: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lessons_late: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lessons_left_early: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lessons_unmeasured: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # #19 diqqat (0-100)
    attention_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # #10 oq xalat: kiygan | kiymagan | aniqlanmadi | talab_yoq
    coat_status: Mapped[str | None] = mapped_column(String, nullable=True)
    coat_samples: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coat_white_samples: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # #15 chekish holatlari (tanilgan odamga bog'langanlari)
    smoking_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # #21/#22 o'qituvchi
    teacher_lessons: Mapped[int | None] = mapped_column(Integer, nullable=True)
    teacher_on_time: Mapped[int | None] = mapped_column(Integer, nullable=True)
    teacher_late: Mapped[int | None] = mapped_column(Integer, nullable=True)
    teacher_absent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    teacher_activity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
