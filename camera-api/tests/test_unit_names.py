"""Production'dagi haqiqiy yozuvlar bilan: lavozimlar (imlo xatolari, kirill)
bo'linma deb olinmasin, bitta bo'linmaning variantlari birlashsin, raqami farq
qiladiganlar esa hech qachon qo'shilmasin."""

import uuid

import pytest

from app.services import situation as svc
from app.services.unit_names import canonical_map, is_position, unit_key


@pytest.mark.parametrize(
    "text",
    [
        "Assistent", "Asisent", "asissent", "Assitent", "ASSISTENT", "Assistant", "Ассистент", "Асиссент",
        "Ассисет", "кафедра ассистенти", "Tashi orindosh.Asistent", "Katta o‘qituvchi", "Katta oqtuvchi",
        "Катта укитувчи", "Stajyor-oʻqituvchi", "stajor o'qituvchi", "O’qituvchi stajer", "Stable-o’qituvchi",
        "Коровул", "Коровл", "Фаррош", "Хисобчи", "Farrosh", "Duradgor", "Durodgor", "Labarant", "Tyutor",
        "Kabinet mudiri", "Kabi net mudiri", "Bosh mutaxassis", "Bo'lim boshlig'i", "1-son TTJ boshligʻi",
        "Professor, tashqi oʻrindosh", "doesn't  PhD", "М.М.Х мухандиси", "Elektramaner", "Xo‘jalik bekasi", "",
    ],
)
def test_positions_are_not_units(text):
    assert is_position(text)


@pytest.mark.parametrize(
    "text",
    [
        "Normal anatomiya", "Pediatriya-2", "Rektorat", "Xisobxona", "Davolash ishi fakulteti",
        "Texnik foydalanish va xo'jalik bo'limi", "1-talabalar turar joyi", "Registrator Office",
        "Endokrinologiya, gematologiya va ftiziatriya kafedrasi", "Ijtimoiy fanlar",
    ],
)
def test_units_are_units(text):
    assert not is_position(text)


def test_unit_key_normalizes_script_and_punctuation():
    assert unit_key("  O‘zbek  va xorijiy-tillar ") == unit_key("O'zbek va xorijiy tillar")
    assert unit_key("Хисобхона") == "xisobxona"


def test_spelling_variants_merge_but_numbers_never_do():
    names = (
        ["Patologik fiziologiya va patologik anatomiya"] * 7
        + ["Potologik fizologiya potologik anatomiya"]
        + ["Devonxona va arxiv"] * 2
        + ["Devonxona va arrived"]
        + ["Pediatriya"] * 14
        + ["Pediatriya-2"] * 11
        + ["1-talabalar turar joyi"] * 9
        + ["3-talabalar turar joyi"] * 9
        + ["Kommunal va mehnat gigienasi"] * 20
        + ["Ovqatlanish, bolalar va o'smirlar gigiyenasi"] * 8
        + ["Assistent"] * 15
    )
    canon = canonical_map(names)
    assert canon[unit_key("Potologik fizologiya potologik anatomiya")] == unit_key(
        "Patologik fiziologiya va patologik anatomiya"
    )
    assert canon[unit_key("Devonxona va arrived")] == unit_key("Devonxona va arxiv")
    assert canon[unit_key("Pediatriya-2")] == unit_key("Pediatriya-2")
    assert canon[unit_key("3-talabalar turar joyi")] == unit_key("3-talabalar turar joyi")
    assert canon[unit_key("Ovqatlanish, bolalar va o'smirlar gigiyenasi")] != unit_key(
        "Kommunal va mehnat gigienasi"
    )
    assert unit_key("Assistent") not in canon


def test_catalog_uses_merged_units_and_puts_positions_in_lavozim():
    staff = [(uuid.uuid4(), "Patologik fiziologiya va patologik anatomiya") for _ in range(3)]
    staff += [(uuid.uuid4(), "Potologik fizologiya potologik anatomiya"), (uuid.uuid4(), "Asisent"),
              (uuid.uuid4(), "Коровул")]
    catalog = svc.build_catalog([], staff)
    real = [u for u in catalog.units.values() if not u.unassigned]
    assert len(real) == 1
    unit = real[0]
    assert unit.name == "Patologik fiziologiya va patologik anatomiya"
    assert len(catalog.staff_ids(unit.id)) == 4
    assert len(catalog.staff_ids(svc.UNASSIGNED_KAFEDRA_ID)) == 2
