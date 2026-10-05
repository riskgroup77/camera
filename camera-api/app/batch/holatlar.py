"""Aniqlangan holat turlari — kunlik tahlil, hisobotlar va dalillar uchun bitta ro'yxat.

Bitta kriteriya kodi bir necha xil holatni bildiradi (#9 — darsdan ham,
ishdan ham erta ketish; #22 — kech kirish ham, umuman kirmaslik ham).
Hisobot har mezon bo'yicha dalilni aniq sanashi uchun har holatga tur
yoziladi (DailyPersonCriteria.details["dalillar"][i]["tur"]).
"""

from __future__ import annotations

# tur -> (kriteriya kodi, qisqa nomi)
TYPES: dict[str, tuple[int | None, str]] = {
    "kech_keldi": (None, "Kech keldi"),  # kod: 6 (xodim) yoki 7 (talaba)
    "ishdan_erta": (9, "Ishdan erta ketdi"),
    "darsda_yoq": (7, "Darsda ko'rinmadi"),
    "darsga_kech": (8, "Darsga kech keldi"),
    "darsdan_erta": (9, "Darsdan erta chiqdi"),
    "xalatsiz": (10, "Oq xalatsiz"),
    "chekish": (15, "Chekish"),
    "diqqat_past": (19, "Darsga diqqati past"),
    "faollik_past": (21, "Darsdagi faolligi past"),
    "oqituvchi_kech": (22, "Darsga kech kirdi"),
    "oqituvchi_kelmadi": (22, "Darsga kirmadi"),
}

LATE = "kech_keldi"
WORK_EARLY = "ishdan_erta"
LESSON_ABSENT = "darsda_yoq"
LESSON_LATE = "darsga_kech"
LESSON_EARLY = "darsdan_erta"
NO_COAT = "xalatsiz"
SMOKING = "chekish"
LOW_ATTENTION = "diqqat_past"
LOW_ACTIVITY = "faollik_past"
TEACHER_LATE = "oqituvchi_kech"
TEACHER_ABSENT = "oqituvchi_kelmadi"


def label(kind: str | None) -> str:
    return TYPES.get(kind or "", (None, ""))[1]


# Eski (tursiz) yozuvlar uchun: kod bo'yicha eng ehtimoliy tur.
_BY_CODE = {6: LATE, 7: LESSON_ABSENT, 8: LESSON_LATE, 9: LESSON_EARLY, 10: NO_COAT, 15: SMOKING,
            19: LOW_ATTENTION, 21: LOW_ACTIVITY, 22: TEACHER_LATE}


def type_of(item: dict) -> str | None:
    """Holat turi; tur yozilmagan eski yozuvda — kod bo'yicha."""
    if item.get("tur"):
        return item["tur"]
    try:
        return _BY_CODE.get(int(item.get("kod") or 0))
    except (TypeError, ValueError):
        return None
