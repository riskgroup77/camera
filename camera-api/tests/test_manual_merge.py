"""Qo'lda birlashtirish (person_dedupe.plan_manual_merge): administrator ikki
yozuvni o'zi tanlaydi — avtomatik qidiruv topa olmaydigan juftlar."""

import json

import pytest

from app.services.person_dedupe import MergeError, merge_candidate_score, plan_manual_merge

FACE = json.dumps([1.0] + [0.0] * 511)
OTHER_FACE = json.dumps([0.0, 1.0] + [0.0] * 510)


def _row(id_, name, **extra):
    row = {"id": id_, "full_name": name, "type": "talaba", "pinfl": None, "hemis_id": None, "active": True,
           "self_registered": False, "biometrics_status": "yoq", "biometric_embedding": None, "att": 0,
           "group_or_position": "", "faculty_id": None,
           "biometric_photo_key": None, "biometric_photo_left_key": None, "biometric_photo_right_key": None}
    row.update(extra)
    return row


def _face(**extra):
    return {"biometrics_status": "tasdiqlangan", "biometric_embedding": FACE, "biometric_photo_key": "a",
            "biometric_photo_left_key": "b", "biometric_photo_right_key": "c", **extra}


def test_surname_changed_face_record_stays_profile_from_hemis():
    """Mamajonova (eski, faol emas, yuz + JSHSHIR) + Kenjayeva (HEMIS, faol,
    guruh, davomat) — yuzli yozuv qoladi, ism/guruh HEMIS'dan, faol bo'ladi."""
    old = _row("old", "Mamajonova Dilbarxon Olimjon qizi", active=False, pinfl="61805056980037",
               group_or_position="4-kurs", **_face())
    hemis = _row("new", "Kenjayeva Dilbarxon Olimjon qizi", hemis_id="H1", group_or_position="3-kurs, TPI-423",
                 faculty_id="F", att=3)
    plan = plan_manual_merge(hemis, old)
    assert plan["keeper"]["id"] == "old" and plan["profile"]["id"] == "new"
    r = plan["result"]
    assert r["full_name"] == "Kenjayeva Dilbarxon Olimjon qizi" and r["group_or_position"] == "3-kurs, TPI-423"
    assert r["active"] and r["biometrics_status"] == "tasdiqlangan" and r["all_angles"]
    assert r["has_pinfl"] and r["hemis_linked"] and r["attendance"] == 3


def test_pending_three_angle_face_is_approved_by_the_merge():
    clone = _row("c", "Dododbayev Azizjon Avazovich", **_face(biometrics_status="kutilmoqda"))
    hemis = _row("h", "Dodobayev Azizjon Avazovich", hemis_id="H2", type="talaba")
    assert plan_manual_merge(clone, hemis)["result"]["biometrics_status"] == "tasdiqlangan"


@pytest.mark.parametrize(
    "a, b, message",
    [
        (_row("a", "X Y"), _row("b", "X Y", type="xodim"), "Talaba va xodim"),
        (_row("a", "X Y", pinfl="11111111111111"), _row("b", "X Y", pinfl="99999999999999"), "ikki xil JSHSHIR"),
        (_row("a", "X Y", **_face()), _row("b", "X Y", **_face(biometric_embedding=OTHER_FACE)), "boshqa-boshqa"),
        (_row("a", "X Y"), _row("a", "X Y"), "Bir xil"),
    ],
)
def test_refuses_different_people(a, b, message):
    with pytest.raises(MergeError, match=message):
        plan_manual_merge(a, b)


def test_typo_in_pinfl_is_not_a_conflict():
    a, b = _row("a", "X Y", pinfl="33011997070019"), _row("b", "X Y", pinfl="33011337070019")
    assert plan_manual_merge(a, b)["result"]["has_pinfl"]


def test_candidates_match_first_name_and_patronymic_across_scripts():
    me = {"full_name": "Muxsinova Nastarinbonu Begzod qizi"}
    assert merge_candidate_score(me, {"full_name": "Мухсинова Настарин Бегзод кизи"}) >= 2
    married = {"full_name": "Kenjayeva Dilbarxon Olimjon qizi"}
    assert merge_candidate_score(married, {"full_name": "Mamajonova Dilbarxon Olimjon qizi"}) == 2
    assert merge_candidate_score(married, {"full_name": "Aliyev Anvar Karimovich"}) == 0


# ── Avtomatik juftlash: yuzli/JSHSHIRli klon <-> HEMIS yozuvi ────────────────

from app.services.person_dedupe import clone_name_match, find_clone_pairs  # noqa: E402


@pytest.mark.parametrize(
    "clone, hemis",
    [
        ("Alijonova Shalola", "Alijonova Shalolaxon Baxtiyorjon qizi"),
        ("Мухсинова Настарин Бегзод кизи", "Muxsinova Nastarinbonu Begzod qizi"),
        ("Shukrona Isojonova", "Isojonova Shukronaxon Abduqayum qizi"),
        ("Sodiqjonov Boburjon Bunyodjon uğli", "Sodiqjonov Bobirjon Bunyodjonovich"),
        ("Fotimaxon Ahmadaliyev Muhiddinjon qizi", "Ahmadaliyeva Fotimaxon Muxiddinjon qizi"),
        ("Abdulahadova Dilafruz Jamoliddin qizi", "Abdulahadova Dilafro'z Jamoliddin qizi"),
    ],
)
def test_clone_spellings_match(clone, hemis):
    assert clone_name_match(clone, hemis, same_group=True)


@pytest.mark.parametrize(
    "clone, hemis, same_group",
    [
        ("Aliyeva Dilnoza Karim qizi", "Aliyeva Dilfuza Karim qizi", True),  # boshqa ism
        ("Karimova Anvara Olim qizi", "Karimova Anvara Saidovna", True),  # otasining ismi boshqa
        ("Mamajonova Dilbarxon Olimjon qizi", "Kenjayeva Dilbarxon Olimjon qizi", False),  # familiya o'zgargan, guruh noma'lum
    ],
)
def test_namesakes_do_not_match(clone, hemis, same_group):
    assert not clone_name_match(clone, hemis, same_group=same_group)


def _r(id_, name, group, **extra):
    row = {"id": id_, "full_name": name, "type": "talaba", "group_or_position": group, "reported_group": None,
           "hemis_id": None, "pinfl": None, "active": False, "self_registered": True,
           "biometrics_status": "yoq", "biometric_embedding": False}
    row.update(extra)
    return row


def test_find_clone_pairs_groups_face_and_pinfl_clones_with_their_hemis_record():
    hemis = _r("h", "Hazratqulova Shaxnozaxon Ibrohimjon qizi", "1-kurs, DI-3426", hemis_id="H", active=True, self_registered=False)
    face = _r("f", "Hazratqulova SHahnoza Ibrohimjon qizi", "3426", biometrics_status="tasdiqlangan", biometric_embedding=True)
    pin = _r("p", "Hazratqulova Shahnoza Ibrohimjon qizi", "3426", pinfl="60509087000056")
    other_group = _r("o", "Hazratqulova Shahnoza Ibrohimjon qizi", "1-kurs, DI-9999", pinfl="1" * 14)
    groups, unsure = find_clone_pairs([hemis, face, pin, other_group])
    assert len(groups) == 1 and not unsure
    target, clones = groups[0]
    assert target["id"] == "h" and {c["id"] for c in clones} == {"f", "p"}


def test_wrong_type_self_registered_clone_pairs_by_group_number():
    hemis = _r("h", "Xusanova Gulbahor Xaydarali qizi", "1-kurs, DI-3626", hemis_id="H", active=True, self_registered=False)
    clone = _r("c", "Xusanova Gulbahor", "3626", type="xodim", biometrics_status="tasdiqlangan", biometric_embedding=True)
    groups, _ = find_clone_pairs([hemis, clone])
    assert len(groups) == 1
    plan = plan_manual_merge(
        {**hemis, "biometric_embedding": None, "att": 0},
        {**clone, "biometric_embedding": FACE, "biometric_photo_key": "a", "biometric_photo_left_key": "b",
         "biometric_photo_right_key": "c", "att": 0},
    )
    assert plan["profile"]["id"] == "h"  # tur, ism, guruh — HEMIS'dan


def test_clone_with_two_candidates_is_left_alone():
    a = _r("a", "Xxx Imran Ahmad Xxx", "1-kurs, MD-0126", hemis_id="H1", active=True)
    b = _r("b", "Xxx Imran Ahmad Xxx", "1-kurs, MD-0126", hemis_id="H2", active=True)
    clone = _r("c", "Imran Ahmad", "2-kurs, MD-0126", biometrics_status="tasdiqlangan", biometric_embedding=True)
    groups, unsure = find_clone_pairs([a, b, clone])
    assert not groups and len(unsure) == 1
