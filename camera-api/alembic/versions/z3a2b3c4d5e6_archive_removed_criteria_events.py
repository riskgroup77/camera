"""Olib tashlangan kriteriyalarning eski hodisalari — arxivga.

Buyurtmachi ro'yxati (2026-10-06): 1 (begona shaxs), 6, 7, 8, 9, 10, 15,
19, 21, 22. Qolgan kriteriyalarning sentyabrdagi hodisalari (ID-badge,
niqob, intizom, uxlash, olomon ...) Hodisalar sahifasi, statistika va
hisobotlarda ko'rinmasin, lekin yo'qolmasin: `events_archive` va
`event_comments_archive` jadvallariga ko'chiriladi (downgrade qaytaradi).
Rasm va kliplar MinIO'da qoladi — tozalash (app/jobs/cleanup.py) faqat
`events` jadvalidagilarni ko'radi.

1-modul (begona shaxs) qatorini app/seed.py ishga tushishda o'zi qo'shadi.

Revision ID: z3a2b3c4d5e6
Revises: z2a2b3c4d5e6
"""

from alembic import op

revision = "z3a2b3c4d5e6"
down_revision = "z2a2b3c4d5e6"
branch_labels = None
depends_on = None

KEPT = (1, 6, 7, 8, 9, 10, 15, 19, 21, 22)
_KEPT_SQL = ", ".join(str(code) for code in KEPT)


def upgrade() -> None:
    op.execute("CREATE TABLE IF NOT EXISTS events_archive (LIKE events INCLUDING DEFAULTS)")
    op.execute("ALTER TABLE events_archive ADD COLUMN IF NOT EXISTS archived_at timestamptz NOT NULL DEFAULT now()")
    op.execute("CREATE TABLE IF NOT EXISTS event_comments_archive (LIKE event_comments INCLUDING DEFAULTS)")
    op.execute(
        f"""INSERT INTO event_comments_archive
            SELECT c.* FROM event_comments c JOIN events e ON e.id = c.event_id
            WHERE e.module_code NOT IN ({_KEPT_SQL})"""
    )
    op.execute(f"INSERT INTO events_archive SELECT e.*, now() FROM events e WHERE e.module_code NOT IN ({_KEPT_SQL})")
    # event_comments — ON DELETE CASCADE (nusxasi yuqorida olingan),
    # unknown_sightings.event_id — ON DELETE SET NULL.
    op.execute(f"DELETE FROM events WHERE module_code NOT IN ({_KEPT_SQL})")


def downgrade() -> None:
    # Ustunlar nomi bilan: arxivda qo'shimcha archived_at bor.
    op.execute(
        """DO $$
        DECLARE cols text;
        BEGIN
          SELECT string_agg(quote_ident(column_name), ', ' ORDER BY ordinal_position) INTO cols
          FROM information_schema.columns WHERE table_name = 'events' AND table_schema = current_schema();
          EXECUTE format('INSERT INTO events (%s) SELECT %s FROM events_archive ON CONFLICT (id) DO NOTHING', cols, cols);
          SELECT string_agg(quote_ident(column_name), ', ' ORDER BY ordinal_position) INTO cols
          FROM information_schema.columns WHERE table_name = 'event_comments' AND table_schema = current_schema();
          EXECUTE format('INSERT INTO event_comments (%s) SELECT %s FROM event_comments_archive ON CONFLICT (id) DO NOTHING',
                         cols, cols);
        END $$"""
    )
    op.execute("DROP TABLE event_comments_archive")
    op.execute("DROP TABLE events_archive")
