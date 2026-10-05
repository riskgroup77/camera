"""HEMIS'ga bog'lanmagan talabalarni moslashtirish (app/services/hemis_reconcile.py)."""

import json

import numpy as np

from app.services.hemis_reconcile import FACE_SAME, MERGE, NOT_FOUND, REVIEW, face_similarity, reconcile


def _vec(seed: int, noise: float = 0.0, base: int | None = None) -> str:
    rng = np.random.default_rng(seed)
    vector = rng.normal(size=512)
    if base is not None:
        vector = np.random.default_rng(base).normal(size=512) + noise * vector
    return json.dumps((vector / np.linalg.norm(vector)).tolist())


def _person(name, group="20.26 gurux", *, id_=None, pinfl=None, face=None):
    return {"id": id_ or f"u:{name}", "full_name": name, "type": "talaba", "group_or_position": group,
            "pinfl": pinfl, "hemis_id": None, "active": True, "biometric_embedding": face}


def _hemis(name, group="1-kurs, Davolash ishi-25", *, id_=None, pinfl=None, face=None, active=True):
    return {"id": id_ or f"h:{name}:{group}", "full_name": name, "type": "talaba", "group_or_position": group,
            "pinfl": pinfl, "hemis_id": f"H-{name}-{group}", "active": active, "biometric_embedding": face}


def _one(unlinked, hemis):
    [proposal] = reconcile(unlinked, hemis)
    return proposal


def test_spelling_variants_link_to_the_only_hemis_student():
    # Kirill, x/h, o'g'li, so'z tartibi — bitta odam.
    p = _one([_person("Махаматова Умидахон")], [_hemis("Mahamatova Umidaxon Rustam qizi"), _hemis("Karimov Sardor")])
    assert p.verdict == MERGE
    assert p.hemis["full_name"] == "Mahamatova Umidaxon Rustam qizi"
    p = _one([_person("Sardor Karimov")], [_hemis("KARIMOV SARDOR BAXODIR O'G'LI")])
    assert p.verdict == MERGE


def test_no_namesake_in_hemis():
    p = _one([_person("Aliyev Anvar")], [_hemis("Valiyev Anvar"), _hemis("Aliyev Sardor")])
    assert p.verdict == NOT_FOUND


def test_different_father_is_not_the_same_student():
    p = _one([_person("Yunusova Dilshoda Akmal qizi")], [_hemis("Yunusova Dilshoda Rustamovna")])
    assert p.verdict == NOT_FOUND


def test_pinfl_conflict_goes_to_review():
    p = _one([_person("Aliyev Anvar", pinfl="12345678901234")], [_hemis("Aliyev Anvar", pinfl="99999999999999")])
    assert p.verdict == REVIEW
    assert "JSHSHIR" in p.reason
    # Bir-ikki raqamdagi xato — o'sha odam.
    p = _one([_person("Aliyev Anvar", pinfl="12345678901234")], [_hemis("Aliyev Anvar", pinfl="12345678901235")])
    assert p.verdict == MERGE


def test_namesakes_resolved_by_group_code():
    hemis = [_hemis("Aliyev Anvar", "2-kurs, DI-3426"), _hemis("Aliyev Anvar", "3-kurs, DI-2301")]
    p = _one([_person("Aliyev Anvar", "1kurs 3426 guruh")], hemis)
    assert p.verdict == MERGE
    assert p.hemis["group_or_position"] == "2-kurs, DI-3426"
    assert len(p.alternatives) == 1
    p = _one([_person("Aliyev Anvar", "bilmayman")], hemis)
    assert p.verdict == REVIEW
    assert len(p.alternatives) == 2


def test_namesakes_resolved_by_face():
    me = _vec(1)
    same = _vec(2, noise=0.5, base=1)  # o'sha odam, boshqa surat
    assert face_similarity({"biometric_embedding": me}, {"biometric_embedding": same}) >= FACE_SAME
    hemis = [_hemis("Aliyev Anvar", "A-1", face=same), _hemis("Aliyev Anvar", "B-2", face=_vec(3))]
    p = _one([_person("Aliyev Anvar", face=me)], hemis)
    assert p.verdict == MERGE
    assert p.hemis["group_or_position"] == "A-1"


def test_different_face_blocks_the_link():
    p = _one([_person("Aliyev Anvar", face=_vec(1))], [_hemis("Aliyev Anvar", face=_vec(9))])
    assert p.verdict == REVIEW
    assert "yuzi boshqa" in p.reason


def test_inactive_hemis_record_needs_review():
    p = _one([_person("Aliyev Anvar")], [_hemis("Aliyev Anvar", active=False)])
    assert p.verdict == REVIEW
    assert "faol emas" in p.reason


def test_one_person_registered_twice_merges_both_into_hemis():
    proposals = reconcile(
        [_person("Aliyev Anvar", id_="a"), _person("Anvar Aliyev", id_="b")], [_hemis("Aliyev Anvar Botirovich")]
    )
    assert [p.verdict for p in proposals] == [MERGE, MERGE]
    assert all("2 marta" in p.reason for p in proposals)


def test_two_different_people_claiming_one_hemis_record_need_review():
    proposals = reconcile(
        [_person("Aliyev Anvar", id_="a", pinfl="11111111111111"), _person("Aliyev Anvar", id_="b", pinfl="99999999999999")],
        [_hemis("Aliyev Anvar Botirovich")],
    )
    assert [p.verdict for p in proposals] == [REVIEW, REVIEW]
    assert all("yana 1 kishi" in p.reason for p in proposals)


def test_hemis_placeholder_and_phone_diacritics():
    # HEMIS chet ellik talabaning yo'q ism qismini "Xxx" bilan to'ldiradi.
    assert _one([_person("Md Arif Raza")], [_hemis("Xxx Md Arif Raza Xxx")]).verdict == MERGE
    # "òĝli" — telefonda terilgan "o'g'li".
    p = _one([_person("Abduvahobov Diyorbek Abduqahhor òĝli")], [_hemis("Abduvahobov Diyorbek Abduqahhor o'g'li")])
    assert p.verdict == MERGE


def test_spelling_difference_goes_to_review_never_merges():
    p = _one([_person("Abdurashidov Abdulaziz", "2301")], [_hemis("Abdurashitov Abdulaziz Karimovich", "2-kurs, DI-2301")])
    assert p.verdict == REVIEW
    assert p.hemis is not None and "imlo" in p.reason and "guruh kodi mos" in p.reason
    # Otasining ismi boshqa — imlo emas, boshqa odam.
    p = _one([_person("Abdurashidov Abdulaziz Olimovich")], [_hemis("Abdurashitov Abdulaziz Karimovich")])
    assert p.verdict == NOT_FOUND


def test_merges_come_first():
    proposals = reconcile(
        [_person("Zokirov Bek"), _person("Aliyev Anvar")], [_hemis("Zokirov Bek")]
    )
    assert [p.verdict for p in proposals] == [MERGE, NOT_FOUND]


def test_same_group_with_a_differently_written_name_goes_to_review():
    hemis = [_hemis("Boymamatov Shamsiddin Bobomurod o'g'li", "1-kurs, S-6226"), _hemis("Karimov Sardor", "1-kurs, S-6226")]
    p = _one([_person("boymamatovshamsiddinbobomurodogli", "6226")], hemis)
    assert p.verdict == REVIEW and "Guruh kodi mos" in p.reason
    assert p.hemis["full_name"].startswith("Boymamatov")
    p = _one([_person("Turaboyev Bunyodjon Popvonjonugʻli", "1-kurs, DI-3426")], [_hemis("Turaboyev Bunyodjon Polvonjon o'g'li", "1-kurs, DI-3426")])
    assert p.verdict == REVIEW
    # Boshqa guruhda — dalil yo'q.
    assert _one([_person("boymamatovshamsiddin", "1111")], hemis).verdict == NOT_FOUND


def test_typed_group_is_matched_only_to_a_real_hemis_group():
    from app.services.hemis_reconcile import NOT_IN_HEMIS, match_hemis_group

    groups = ["1-kurs, DI-2426", "2-kurs, TPI-926", "DI-4626"]
    assert match_hemis_group("1-kurs, DI-2426", groups) == "1-kurs, DI-2426"
    assert match_hemis_group(" di-2426 ", groups) == "1-kurs, DI-2426"  # faqat nomi
    assert match_hemis_group("DI-4626", groups) == "DI-4626"  # kursi aniqlanmagan HEMIS guruhi
    for typed in ("2426", "20.26 gurux", "1-kurs", "", None, NOT_IN_HEMIS):
        assert match_hemis_group(typed, groups) is None


def test_group_evidence_survives_moving_to_not_in_hemis():
    from app.services.hemis_reconcile import NOT_IN_HEMIS

    person = _person("Aliyev Anvar", NOT_IN_HEMIS)
    person["reported_group"] = "1kurs 3426 guruh"
    hemis = [_hemis("Aliyev Anvar", "2-kurs, DI-3426"), _hemis("Aliyev Anvar", "3-kurs, DI-2301")]
    p = _one([person], hemis)
    assert p.verdict == MERGE and p.hemis["group_or_position"] == "2-kurs, DI-3426"
