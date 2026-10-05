"""Kunlik video tahlil: NVR, tahlil ishlari, kuzatuvlar, kunlik natijalar;
kriteriyalar ro'yxati buyurtmachi qaroriga moslandi (2026-10-04).

Qoldi: 6, 7, 8, 9, 10, 15, 19, 21, 22. Olib tashlandi: 1, 2, 3, 20, 26.
Oq xalat (10) va chekish (15) qaytdi — endi kun oxirida videodan ko'p
namuna bilan hisoblanadi (docs/KUNLIK_VIDEO_TAHLIL.md).

Revision ID: z1a2b3c4d5e6
Revises: s2a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "z1a2b3c4d5e6"
down_revision = "s2a2b3c4d5e6"
branch_labels = None
depends_on = None

REMOVED = (1, 2, 3, 20, 26)

_UUID = postgresql.UUID(as_uuid=True)
_ID = sa.Column("id", _UUID, primary_key=True, server_default=sa.text("gen_random_uuid()"))
_TS = sa.DateTime(timezone=True)

NEW_MODULES = [
    (
        10,
        "C",
        "Oq xalat kiyilganligi",
        "Tibbiy xodim/talabaning oq xalatda ekanligi — kun oxirida videodan: tanilgan yuz ostidagi tana sohasi "
        "(YOLO odam ramkasi bilan chegaralangan) oq rang ulushi o'lchanadi, kun bo'yi ko'p namunadan ovoz beriladi.",
        "Yuz tanish + YOLO odam ramkasi + rang tahlili (yoki o'qitilgan klassifikator) + kunlik ovoz berish "
        "(app/batch/coat.py)",
        "o'rta",
    ),
    (
        15,
        "D",
        "Chekish / elektron sigareta",
        "Bino ichida yoki hovlida chekish holatlari — tashqi va koridor kameralarining 20 soniyalik kliplarida "
        "odam pozasi kuzatiladi: qo'lning og'izga takroriy ko'tarilishi; telefon/stakan bo'lsa rad etiladi.",
        "YOLO poza + qo'l-og'iz takroriy harakati + obyekt istisnolari (ixtiyoriy sigaret modeli) "
        "(app/batch/smoking.py)",
        "past",
    ),
]


def upgrade() -> None:
    op.create_table(
        "nvr_devices",
        _ID.copy(),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False, server_default="hikvision"),
        sa.Column("ip", sa.String(), nullable=True),
        sa.Column("http_port", sa.Integer(), nullable=False, server_default="80"),
        sa.Column("rtsp_port", sa.Integer(), nullable=False, server_default="554"),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("password", sa.String(), nullable=True),
        sa.Column("stream", sa.String(), nullable=False, server_default="main"),
        sa.Column("fetch_mode", sa.String(), nullable=False, server_default="download"),
        sa.Column("max_streams", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("local_time", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "rtsp_path_template",
            sa.String(),
            nullable=False,
            server_default="/Streaming/tracks/{channel}0{stream}?starttime={start}&endtime={end}",
        ),
        sa.Column("base_path", sa.String(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_check_at", _TS, nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("channel_count", sa.Integer(), nullable=True),
        sa.Column("created_at", _TS, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('hikvision', 'fayl')", name="ck_nvr_devices_kind"),
        sa.CheckConstraint("stream IN ('main', 'sub')", name="ck_nvr_devices_stream"),
        sa.CheckConstraint("fetch_mode IN ('rtsp', 'download')", name="ck_nvr_devices_fetch_mode"),
    )
    op.add_column("cameras", sa.Column("nvr_id", _UUID, nullable=True))
    op.add_column("cameras", sa.Column("nvr_channel", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_cameras_nvr_id", "cameras", "nvr_devices", ["nvr_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_cameras_nvr_id", "cameras", ["nvr_id"])

    op.create_table(
        "video_analysis_runs",
        _ID.copy(),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("window_start", _TS, nullable=False),
        sa.Column("window_end", _TS, nullable=False),
        sa.Column("created_at", _TS, server_default=sa.func.now()),
        sa.Column("started_at", _TS, nullable=True),
        sa.Column("finished_at", _TS, nullable=True),
        sa.Column("jobs_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("jobs_done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("jobs_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("jobs_no_video", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("frames_planned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("frames_analyzed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("faces_detected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("observations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stats", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("triggered_by", sa.String(), nullable=False, server_default="tizim"),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.CheckConstraint(
            "status IN ('navbatda', 'ishlamoqda', 'agregatsiya', 'tugadi', 'xato', 'bekor')",
            name="ck_video_analysis_runs_status",
        ),
    )
    op.create_index("ix_video_analysis_runs_day", "video_analysis_runs", ["day"])

    op.create_table(
        "video_analysis_jobs",
        _ID.copy(),
        sa.Column("run_id", _UUID, sa.ForeignKey("video_analysis_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("camera_id", _UUID, sa.ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "lesson_session_id", _UUID, sa.ForeignKey("lesson_sessions.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("clips", postgresql.JSONB(), nullable=False),
        sa.Column("start_at", _TS, nullable=False),
        sa.Column("end_at", _TS, nullable=False),
        sa.Column("frames_planned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("frames", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("faces", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("observations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("covered", postgresql.JSONB(), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", _TS, nullable=True),
        sa.Column("finished_at", _TS, nullable=True),
        sa.CheckConstraint(
            "status IN ('navbatda', 'ishlamoqda', 'tugadi', 'xato', 'yozuv_yoq', 'bekor')",
            name="ck_video_analysis_jobs_status",
        ),
    )
    op.create_index("ix_video_analysis_jobs_run_status", "video_analysis_jobs", ["run_id", "status"])

    op.create_table(
        "video_observations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", _UUID, sa.ForeignKey("video_analysis_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", _UUID, sa.ForeignKey("video_analysis_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("camera_id", _UUID, sa.ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "student_staff_id", _UUID, sa.ForeignKey("students_staff.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("seen_at", _TS, nullable=False),
        sa.Column("last_seen_at", _TS, nullable=False),
        sa.Column("similarity", sa.Float(), nullable=False),
        sa.Column("margin", sa.Float(), nullable=False),
        sa.Column("frames", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("face_px", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("frontal_frames", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("phone_frames", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("coat_frames", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("coat_white_frames", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("coat_fraction", sa.Float(), nullable=True),
        sa.Column("movement", sa.Float(), nullable=True),
        sa.Column("clip_index", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("evidence_key", sa.String(), nullable=True),
    )
    op.create_index("ix_video_observations_day_person", "video_observations", ["day", "student_staff_id"])
    op.create_index("ix_video_observations_job", "video_observations", ["job_id"])
    op.create_index("ix_video_observations_run", "video_observations", ["run_id"])

    op.create_table(
        "daily_person_criteria",
        _ID.copy(),
        sa.Column(
            "student_staff_id", _UUID, sa.ForeignKey("students_staff.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("run_id", _UUID, sa.ForeignKey("video_analysis_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("attendance_status", sa.String(), nullable=True),
        sa.Column("arrived_at", _TS, nullable=True),
        sa.Column("left_at", _TS, nullable=True),
        sa.Column("late_minutes", sa.Integer(), nullable=True),
        sa.Column("early_leave", sa.String(), nullable=True),
        sa.Column("sightings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cameras_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lessons_total", sa.Integer(), nullable=True),
        sa.Column("lessons_attended", sa.Integer(), nullable=True),
        sa.Column("lessons_late", sa.Integer(), nullable=True),
        sa.Column("lessons_left_early", sa.Integer(), nullable=True),
        sa.Column("lessons_unmeasured", sa.Integer(), nullable=True),
        sa.Column("attention_score", sa.Integer(), nullable=True),
        sa.Column("coat_status", sa.String(), nullable=True),
        sa.Column("coat_samples", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("coat_white_samples", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("smoking_events", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("teacher_lessons", sa.Integer(), nullable=True),
        sa.Column("teacher_on_time", sa.Integer(), nullable=True),
        sa.Column("teacher_late", sa.Integer(), nullable=True),
        sa.Column("teacher_absent", sa.Integer(), nullable=True),
        sa.Column("teacher_activity", sa.Integer(), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Column("computed_at", _TS, server_default=sa.func.now()),
        sa.UniqueConstraint("student_staff_id", "day", name="uq_daily_person_criteria"),
    )
    op.create_index("ix_daily_person_criteria_day", "daily_person_criteria", ["day"])

    op.add_column("lesson_attendance", sa.Column("left_early", sa.Boolean(), nullable=True))
    op.add_column("lesson_attendance", sa.Column("attention_score", sa.Integer(), nullable=True))
    op.add_column(
        "lesson_attendance", sa.Column("attention_samples", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("lesson_sessions", sa.Column("teacher_first_seen_at", _TS, nullable=True))
    op.add_column("lesson_sessions", sa.Column("teacher_presence_pct", sa.Integer(), nullable=True))

    # Kriteriyalar ro'yxati (y1a2b3c4d5e6 bilan bir xil tartib).
    codes = ", ".join(str(code) for code in REMOVED)
    op.execute(f"DELETE FROM module_camera_suppressions WHERE module_code IN ({codes})")
    op.execute(f"DELETE FROM ai_modules WHERE code IN ({codes})")
    op.execute(
        f"""
        UPDATE notification_rules
        SET module_codes = COALESCE(
            (SELECT jsonb_agg(value) FROM jsonb_array_elements(module_codes) AS value
             WHERE value::text::int NOT IN ({codes})),
            '[]'::jsonb)
        WHERE module_codes IS NOT NULL AND jsonb_typeof(module_codes) = 'array'
        """
    )
    modules = sa.table(
        "ai_modules",
        sa.column("code", sa.Integer),
        sa.column("group", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("method", sa.String),
        sa.column("accuracy", sa.Float),
        sa.column("threshold", sa.Integer),
        sa.column("sensitivity", sa.String),
        sa.column("camera_count", sa.Integer),
        sa.column("active", sa.Boolean),
        sa.column("has_detector", sa.Boolean),
        sa.column("mode", sa.String),
    )
    conn = op.get_bind()
    existing = {row[0] for row in conn.execute(sa.text("SELECT code FROM ai_modules"))}
    rows = [
        {
            "code": code,
            "group": group,
            "name": name,
            "description": description,
            "method": method,
            "accuracy": 0.0,
            "threshold": 50,
            "sensitivity": sensitivity,
            "camera_count": 0,
            "active": True,
            "has_detector": True,
            # Kalibrlanmagan — hodisalari avval operator tekshiruviga.
            "mode": "sinov",
        }
        for code, group, name, description, method, sensitivity in NEW_MODULES
        if code not in existing
    ]
    if rows:
        op.bulk_insert(modules, rows)
    # Talaba davomati (7) ilgari to'xtatilgan edi (l5f6a7b8c9d0) — kunlik
    # tahlilda dars xonalari ham ko'riladi, u yana yoqiladi.
    op.execute("UPDATE ai_modules SET active = true WHERE code = 7")


def downgrade() -> None:
    op.execute("DELETE FROM ai_modules WHERE code IN (10, 15)")
    op.drop_column("lesson_sessions", "teacher_presence_pct")
    op.drop_column("lesson_sessions", "teacher_first_seen_at")
    op.drop_column("lesson_attendance", "attention_samples")
    op.drop_column("lesson_attendance", "attention_score")
    op.drop_column("lesson_attendance", "left_early")
    op.drop_index("ix_daily_person_criteria_day", table_name="daily_person_criteria")
    op.drop_table("daily_person_criteria")
    op.drop_table("video_observations")
    op.drop_table("video_analysis_jobs")
    op.drop_table("video_analysis_runs")
    op.drop_index("ix_cameras_nvr_id", table_name="cameras")
    op.drop_constraint("fk_cameras_nvr_id", "cameras", type_="foreignkey")
    op.drop_column("cameras", "nvr_channel")
    op.drop_column("cameras", "nvr_id")
    op.drop_table("nvr_devices")
