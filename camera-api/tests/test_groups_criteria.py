"""Nazorat → "Kriteriyalar bo'yicha": guruh kataklari (hisobot bilan bir xil hisob)."""

import uuid
from datetime import date

from app.services import hisobot
from app.services.attendance_policy import Policy


def _member(enrolled: bool) -> hisobot.Member:
    return hisobot.Member(uuid.uuid4(), "Talaba", "1-kurs, TPI-126", None, None, enrolled)


def test_attendance_counts_only_registered_students():
    """Davomat — "kelgan / ro'yxatdan o'tgan" (Nazorat qoidasi: ro'yxatdan
    o'tmaganlar HEMIS bo'yicha kelgan bo'lsa ham sanalmaydi)."""
    people = [_member(True) for _ in range(4)] + [_member(False) for _ in range(3)]
    day = date(2026, 10, 6)
    data = hisobot.Data("talaba", day, day, Policy(), people)
    data.day_rows = {
        people[0].id: {"status": "keldi"},
        people[1].id: {"status": "kech_keldi"},
        people[4].id: {"status": "keldi"},  # ro'yxatdan o'tmagan — sanalmaydi
    }
    data.active_modules = {6, 7, 8, 9, 10, 15, 19, 21, 22}
    cell = hisobot.group_cell(data, "davomat", analysed=False)
    assert cell["value"] == "2/4" and "4 talabadan 2" in cell["title"]
    assert hisobot.group_cell(data, "kechikish", analysed=False)["value"] == "1"


def test_hidden_lesson_criteria_are_not_columns():
    assert set(hisobot.HIDDEN_IN_GROUP) == {"dars_qatnashish", "darsga_kech", "darsdan_erta"}
