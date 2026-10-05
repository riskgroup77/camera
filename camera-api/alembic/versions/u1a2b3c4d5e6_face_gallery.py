"""Kamera-domen yuz galereyasi (face_gallery_embeddings).

Revision ID: u1a2b3c4d5e6
Revises: t1a2b3c4d5e6
Create Date: 2026-09-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "u1a2b3c4d5e6"
down_revision = "t1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "face_gallery_embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "student_staff_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("students_staff.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("embedding", sa.String(), nullable=False),
        sa.Column("anchor_hash", sa.String(64), nullable=False),
        sa.Column("similarity", sa.Float(), nullable=False),
        sa.Column("face_px", sa.Integer(), nullable=False),
        sa.Column(
            "camera_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_face_gallery_embeddings_student_staff_id", "face_gallery_embeddings", ["student_staff_id"]
    )
    # Biometrika o'chirilsa yoki odam qayta ro'yxatdan o'tsa — kamera
    # namunalari ham shu zahoti o'chadi (maxfiylik: vektor qolib ketmasin).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION face_gallery_purge_on_anchor_change() RETURNS trigger AS $$
        BEGIN
            IF NEW.biometric_embedding IS DISTINCT FROM OLD.biometric_embedding THEN
                DELETE FROM face_gallery_embeddings WHERE student_staff_id = NEW.id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_face_gallery_purge
        AFTER UPDATE OF biometric_embedding ON students_staff
        FOR EACH ROW EXECUTE FUNCTION face_gallery_purge_on_anchor_change();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_face_gallery_purge ON students_staff")
    op.execute("DROP FUNCTION IF EXISTS face_gallery_purge_on_anchor_change()")
    op.drop_index("ix_face_gallery_embeddings_student_staff_id", table_name="face_gallery_embeddings")
    op.drop_table("face_gallery_embeddings")
