"""P1 scale indexes — model metadata matches production migration."""

from app.models.attendance import AttendanceRecord
from app.models.event import Event


class TestScaleIndexMetadata:
    def test_attendance_date_index_declared(self):
        names = {idx.name for idx in AttendanceRecord.__table__.indexes}
        assert "ix_attendance_records_date" in names
        assert "ix_attendance_records_date_status" in names

    def test_attendance_date_index_columns(self):
        by_name = {idx.name: idx for idx in AttendanceRecord.__table__.indexes}
        assert [c.name for c in by_name["ix_attendance_records_date"].columns] == ["date"]
        assert [c.name for c in by_name["ix_attendance_records_date_status"].columns] == ["date", "status"]

    def test_events_dedup_composite_index_declared(self):
        names = {idx.name for idx in Event.__table__.indexes}
        assert "ix_events_camera_module_occurred" in names

    def test_events_dedup_index_column_order(self):
        idx = next(i for i in Event.__table__.indexes if i.name == "ix_events_camera_module_occurred")
        assert [c.name for c in idx.columns] == ["camera_id", "module_code", "occurred_at"]

    def test_events_occurred_at_index_still_present(self):
        """Admin list + cleanup retain the original single-column index."""
        occurred = [i for i in Event.__table__.indexes if "occurred_at" in {c.name for c in i.columns}]
        assert any(i.name == "ix_events_occurred_at" for i in occurred)
