"""Bir kunlik davomat HEMIS'dan (app/services/hemis_attendance.py)."""

from app.services.hemis_attendance import day_attendance


def _control(group, pair, teacher):
    return {"group": {"id": group}, "lessonPair": {"code": pair}, "employee": {"id": teacher}}


def _absent(student, pair, on=0, off=2):
    return {"student": {"id": student}, "lessonPair": {"code": pair}, "absent_on": on, "absent_off": off}


def test_present_if_not_absent_from_every_lesson():
    controls = [_control("G1", "1", "T1"), _control("G1", "2", "T2"), _control("G2", "1", "T3")]
    absences = [
        _absent("ali", "1"), _absent("ali", "2"),  # hamma darsda yo'q -> kelmadi
        _absent("vali", "1"),  # bitta darsda yo'q -> keldi
        _absent("soli", "1", on=0, off=0),  # 0 soat — yo'qlik emas
    ]
    out = day_attendance(controls, absences, {"G1": ["ali", "vali", "soli", "guli"], "G2": [], "G3": ["x"]})
    assert out.students == {"ali": "kelmadi", "vali": "keldi", "soli": "keldi", "guli": "keldi"}
    # Davomati olinmagan guruh (G3) — yozuv yo'q; talabasi topilmagan guruh sanaladi.
    assert "x" not in out.students
    assert out.groups_checked == 1 and out.groups_without_students == 1
    assert out.teachers == {"T1", "T2", "T3"}


def test_excused_absence_is_still_absence():
    out = day_attendance([_control("G", "1", "T")], [_absent("ali", "1", on=2, off=0)], {"G": ["ali"]})
    assert out.students == {"ali": "kelmadi"}
