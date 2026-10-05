"""Platforma kengaytmasi: bildirishnomalar, hodisa ish jarayoni, qavat
rejalari, PTZ, turniket, HEMIS, rozilik va saqlash muddati.

Revision ID: s1a2b3c4d5e6
Revises: r2b3c4d5e6f7
Create Date: 2026-09-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "s1a2b3c4d5e6"
down_revision = "r2b3c4d5e6f7"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB()

# (super_admin, admin, kamera_masuli) — app/seed.py DEFAULT_PERMISSIONS bilan bir xil.
NEW_PERMISSIONS = {
    "manageNotifications": (True, True, False),
    "manageIntegrations": (True, False, False),
    "controlPtz": (True, True, False),
    "managePrivacy": (True, False, False),
}


def _id_col() -> sa.Column:
    return sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _created_col(name: str = "created_at") -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    # --- cameras: PTZ va qavat rejasidagi joy ---
    op.add_column("cameras", sa.Column("ptz_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("cameras", sa.Column("ptz_protocol", sa.String(), nullable=True))
    op.add_column("cameras", sa.Column("onvif_port", sa.Integer(), nullable=True))
    op.add_column("cameras", sa.Column("plan_x", sa.Float(), nullable=True))
    op.add_column("cameras", sa.Column("plan_y", sa.Float(), nullable=True))
    op.add_column("cameras", sa.Column("plan_rotation", sa.SmallInteger(), nullable=True))
    op.create_check_constraint(
        "ck_cameras_ptz_protocol", "cameras", "ptz_protocol IS NULL OR ptz_protocol IN ('onvif', 'isapi')"
    )

    # --- events: ish jarayoni ---
    op.drop_constraint("ck_events_status", "events", type_="check")
    op.create_check_constraint(
        "ck_events_status",
        "events",
        "status IN ('yangi', 'jarayonda', 'tasdiqlangan', 'rad_etilgan', 'hal_qilindi')",
    )
    op.add_column(
        "events",
        sa.Column("assigned_to_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column("events", sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("events", sa.Column("due_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("events", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("events", sa.Column("resolved_by", sa.String(), nullable=True))
    op.add_column("events", sa.Column("resolution_note", sa.Text(), nullable=True))
    op.add_column("events", sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_events_assigned_status", "events", ["assigned_to_id", "status"])

    # --- students_staff ---
    op.add_column("students_staff", sa.Column("parent_phone", sa.String(20), nullable=True))
    op.add_column("students_staff", sa.Column("parent_telegram_chat_id", sa.String(), nullable=True))
    op.add_column(
        "students_staff",
        sa.Column("parent_notify_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("students_staff", sa.Column("telegram_link_code", sa.String(32), nullable=True))
    op.create_unique_constraint("uq_students_staff_telegram_link_code", "students_staff", ["telegram_link_code"])
    op.add_column("students_staff", sa.Column("card_number", sa.String(), nullable=True))
    op.create_index("ix_students_staff_card_number", "students_staff", ["card_number"], unique=True)
    op.add_column("students_staff", sa.Column("hemis_id", sa.String(), nullable=True))
    op.create_index("ix_students_staff_hemis_id", "students_staff", ["hemis_id"], unique=True)
    op.add_column("students_staff", sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("students_staff", sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("students_staff", sa.Column("consent_given_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("students_staff", sa.Column("consent_version", sa.String(), nullable=True))
    op.add_column("students_staff", sa.Column("consent_source", sa.String(), nullable=True))

    # --- users ---
    op.add_column("users", sa.Column("phone", sa.String(20), nullable=True))
    op.add_column("users", sa.Column("telegram_chat_id", sa.String(), nullable=True))
    op.add_column("users", sa.Column("telegram_link_code", sa.String(32), nullable=True))
    op.create_unique_constraint("uq_users_telegram_link_code", "users", ["telegram_link_code"])

    # --- attendance_records ---
    op.add_column("attendance_records", sa.Column("source", sa.String(), nullable=True))

    # --- yangi jadvallar ---
    op.create_table(
        "notification_rules",
        _id_col(),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("recipients", JSONB, nullable=False),
        sa.Column("kinds", JSONB, nullable=False),
        sa.Column("module_codes", JSONB, nullable=True),
        sa.Column("building_ids", JSONB, nullable=True),
        sa.Column("min_severity", sa.String(), nullable=True),
        _created_col(),
        sa.CheckConstraint("channel IN ('telegram', 'sms')", name="ck_notification_rules_channel"),
        sa.CheckConstraint(
            "min_severity IS NULL OR min_severity IN ('past', 'o''rta', 'yuqori')",
            name="ck_notification_rules_min_severity",
        ),
    )
    op.create_table(
        "notification_log",
        _id_col(),
        _created_col(),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("recipient", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("ref_id", sa.String(), nullable=True),
        sa.CheckConstraint("status IN ('yuborildi', 'xato', 'otkazildi')", name="ck_notification_log_status"),
    )
    op.create_index("ix_notification_log_created", "notification_log", ["created_at"])

    op.create_table(
        "event_comments",
        _id_col(),
        sa.Column("event_id", UUID, sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("author_name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False, server_default="izoh"),
        sa.Column("body", sa.Text(), nullable=False),
        _created_col(),
        sa.CheckConstraint("kind IN ('izoh', 'holat', 'tayinlash')", name="ck_event_comments_kind"),
    )
    op.create_index("ix_event_comments_event_id", "event_comments", ["event_id"])

    op.create_table(
        "floor_plans",
        _id_col(),
        sa.Column("building_id", UUID, sa.ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("floor", sa.SmallInteger(), nullable=False),
        sa.Column("name", sa.String(), nullable=False, server_default=""),
        sa.Column("image_key", sa.String(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("height", sa.Integer(), nullable=False, server_default="0"),
        _created_col(),
        sa.UniqueConstraint("building_id", "floor", name="uq_floor_plans_building_floor"),
    )
    op.create_index("ix_floor_plans_building_id", "floor_plans", ["building_id"])

    op.create_table(
        "access_devices",
        _id_col(),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("ip", sa.String(), nullable=True),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("password", sa.String(), nullable=True),
        sa.Column("api_key_hash", sa.String(), nullable=True),
        sa.Column("direction", sa.String(), nullable=False, server_default="kirish"),
        sa.Column("building_id", UUID, sa.ForeignKey("buildings.id", ondelete="SET NULL"), nullable=True),
        sa.Column("marks_attendance", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_poll_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("poll_cursor", sa.String(), nullable=True),
        _created_col(),
        sa.CheckConstraint("kind IN ('hikvision', 'zkteco', 'webhook')", name="ck_access_devices_kind"),
        sa.CheckConstraint(
            "direction IN ('kirish', 'chiqish', 'ikkalasi')", name="ck_access_devices_direction"
        ),
    )
    op.create_table(
        "access_events",
        _id_col(),
        sa.Column("device_id", UUID, sa.ForeignKey("access_devices.id", ondelete="SET NULL"), nullable=True),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("card_number", sa.String(), nullable=True),
        sa.Column("employee_no", sa.String(), nullable=True),
        sa.Column(
            "student_staff_id", UUID, sa.ForeignKey("students_staff.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("direction", sa.String(), nullable=True),
        sa.Column("granted", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("raw", JSONB, nullable=True),
        _created_col(),
        sa.UniqueConstraint("device_id", "external_id", name="uq_access_events_device_external"),
    )
    op.create_index("ix_access_events_occurred", "access_events", ["occurred_at"])
    op.create_index("ix_access_events_device_id", "access_events", ["device_id"])
    op.create_index("ix_access_events_student_staff_id", "access_events", ["student_staff_id"])

    op.create_table(
        "integration_sync_runs",
        _id_col(),
        sa.Column("source", sa.String(), nullable=False),
        _created_col("started_at"),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="ishlamoqda"),
        sa.Column("stats", JSONB, nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("triggered_by", sa.String(), nullable=False, server_default="tizim"),
        sa.CheckConstraint(
            "status IN ('ishlamoqda', 'muvaffaqiyatli', 'xato')", name="ck_integration_sync_runs_status"
        ),
    )
    op.create_index(
        "ix_integration_sync_runs_source_started", "integration_sync_runs", ["source", "started_at"]
    )

    # --- yangi huquqlar (seed faqat bo'sh bazani to'ldiradi) ---
    permissions = sa.table(
        "permissions",
        sa.column("key", sa.String),
        sa.column("super_admin", sa.Boolean),
        sa.column("admin", sa.Boolean),
        sa.column("camera_steward", sa.Boolean),
    )
    conn = op.get_bind()
    existing = {row[0] for row in conn.execute(sa.select(permissions.c.key))}
    rows = [
        {"key": key, "super_admin": sa_, "admin": ad, "camera_steward": cs}
        for key, (sa_, ad, cs) in NEW_PERMISSIONS.items()
        if key not in existing
    ]
    # Bo'sh baza (yangi o'rnatish) — seed hammasini o'zi yozadi.
    if existing and rows:
        op.bulk_insert(permissions, rows)


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM permissions WHERE key IN :keys").bindparams(
            sa.bindparam("keys", expanding=True, value=list(NEW_PERMISSIONS))
        )
    )
    op.drop_table("integration_sync_runs")
    op.drop_table("access_events")
    op.drop_table("access_devices")
    op.drop_table("floor_plans")
    op.drop_table("event_comments")
    op.drop_table("notification_log")
    op.drop_table("notification_rules")

    op.drop_column("attendance_records", "source")

    op.drop_constraint("uq_users_telegram_link_code", "users", type_="unique")
    for col in ("telegram_link_code", "telegram_chat_id", "phone"):
        op.drop_column("users", col)

    op.drop_index("ix_students_staff_hemis_id", table_name="students_staff")
    op.drop_index("ix_students_staff_card_number", table_name="students_staff")
    op.drop_constraint("uq_students_staff_telegram_link_code", "students_staff", type_="unique")
    for col in (
        "consent_source",
        "consent_version",
        "consent_given_at",
        "deactivated_at",
        "active",
        "hemis_id",
        "card_number",
        "telegram_link_code",
        "parent_notify_enabled",
        "parent_telegram_chat_id",
        "parent_phone",
    ):
        op.drop_column("students_staff", col)

    op.drop_index("ix_events_assigned_status", table_name="events")
    for col in (
        "escalated_at",
        "resolution_note",
        "resolved_by",
        "resolved_at",
        "due_at",
        "assigned_at",
        "assigned_to_id",
    ):
        op.drop_column("events", col)
    op.execute("UPDATE events SET status = 'tasdiqlangan' WHERE status IN ('jarayonda', 'hal_qilindi')")
    op.drop_constraint("ck_events_status", "events", type_="check")
    op.create_check_constraint("ck_events_status", "events", "status IN ('yangi', 'tasdiqlangan', 'rad_etilgan')")

    op.drop_constraint("ck_cameras_ptz_protocol", "cameras", type_="check")
    for col in ("plan_rotation", "plan_y", "plan_x", "onvif_port", "ptz_protocol", "ptz_enabled"):
        op.drop_column("cameras", col)
