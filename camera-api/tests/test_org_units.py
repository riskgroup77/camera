"""Institut tuzilmasi — HEMIS bo'linmalari (app/services/org_structure.py)."""

import uuid

from app.services.org_structure import (
    TreeUnit,
    build_tree,
    descendants,
    match_unit,
    org_kind,
    position_group,
    unit_key,
)


def test_kinds_from_hemis_codes():
    assert org_kind("11", "Pediatriya fakulteti") == "fakultet"
    assert org_kind("11", "Magistratura boʻlimi") == "oquv"
    assert org_kind("11", "Malaka oshirish va qayta tayyorlash fakulteti") == "oquv"
    assert org_kind("12", "Anatomiya") == "kafedra"
    assert org_kind("16", "Rektorat") == "rektorat"
    assert org_kind("10", "1-talabalar turar joyi") == "turar_joy"
    assert org_kind("10", "Vivariylar") == "boshqa"
    assert org_kind(None, "Nomaʼlum") == "boshqa"


def test_position_groups():
    assert position_group("Assistent") == "oqituvchi"
    assert position_group("Stajer-o‘qituvchi") == "oqituvchi"
    assert position_group("Kafedra mudiri") == "oqituvchi"
    assert position_group("Farrosh") == "texnik"
    assert position_group("Qorovul") == "texnik"
    assert position_group("Ko‘cha supuruvchi") == "texnik"
    assert position_group("Chilangar (santexnik)") == "texnik"
    assert position_group("Hisobchi") == "mamuriy"
    assert position_group("Bo‘lim boshlig‘i") == "mamuriy"
    assert position_group(None) is None


def test_unassigned_staff_match_by_unit_name():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    keys = {unit_key("Pediatriya"): a, unit_key("Yu. Nishonov nomidagi Normal anatomiya"): b, unit_key("Xisobxona"): c}
    assert match_unit("Pediatriya kafedrasi", keys) == a
    assert match_unit("Normal anatomiya kafedrasi", keys) == b
    assert match_unit("Hisobxona", keys) == c  # x/h farqi
    assert match_unit("Qorovullar", keys) is None


def test_tree_order_and_descendants():
    fac, kaf, rek, bolim = (uuid.uuid4() for _ in range(4))

    class U:
        def __init__(self, id, name, kind, parent_id=None):
            self.id, self.name, self.kind, self.parent_id = id, name, kind, parent_id

    roots = build_tree([
        U(bolim, "Xisobxona", "bolim"), U(kaf, "Pediatriya", "kafedra", fac),
        U(fac, "Pediatriya fakulteti", "fakultet"), U(rek, "Rektorat", "rektorat"),
    ])
    assert [r.kind for r in roots] == ["rektorat", "fakultet", "bolim"]
    assert isinstance(roots[1].children[0], TreeUnit) and roots[1].children[0].id == kaf
    assert descendants(roots, fac) == {fac, kaf}
    assert descendants(roots, kaf) == {kaf}


def test_hand_typed_positions_are_normalised():
    from app.services.org_structure import canonical_position

    for text, expected in [
        ("Assisent", "Assistent"), ("asissent", "Assistent"), ("Ассистент", "Assistent"), ("кафедра ассистенти", "Assistent"),
        ("stajyor o'qituvchi", "Stajer-o‘qituvchi"), ("O'qituvchi stajer", "Stajer-o‘qituvchi"),
        ("Katta oqtuvchi", "Katta o‘qituvchi"), ("Фаррош", "Farrosh"), ("Коровл", "Qorovul"),
        ("Durodgor", "Duradgor"), ("Elektramaner", "Elektromontyor"), ("Хисобчи", "Hisobchi"),
        ("Kabi net mudiri", "Kabinet mudiri"), ("Labarant", "Laborant"), ("O’qituvchi", "O‘qituvchi"),
    ]:
        assert canonical_position(text) == expected, text
    assert canonical_position("1-son TTJ boshligʻi") == "1-son TTJ boshligʻi"
    assert position_group("Фаррош") == "texnik" and position_group("Assisent") == "oqituvchi"


def test_unit_catalog_prefers_hemis_units():
    """Kafedralar sahifasi: HEMIS bo'linmasiga bog'langan xodim o'sha bo'linmada;
    bog'lanmagan xodim eski matn bo'yicha, lekin nomi mos bo'lsa HEMIS bo'linmasiga."""
    from app.services import situation as svc

    anatomy, rector, dorm = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    a, b, c, d = (uuid.uuid4() for _ in range(4))
    catalog = svc.build_catalog(
        [svc.DepartmentInfo(uuid.uuid4(), "Anatomiya kafedrasi", "A bino")],
        [(a, f"org:{anatomy}"), (b, "Anatomiya kafedrasi"), (c, f"org:{rector}"), (d, "Farrosh")],
        [svc.OrgUnitInfo(anatomy, "Anatomiya kafedrasi", "kafedra"), svc.OrgUnitInfo(rector, "Rektorat", "rektorat"),
         svc.OrgUnitInfo(dorm, "1-talabalar turar joyi", "turar_joy")],
    )
    assert catalog.unit_id(f"org:{anatomy}") == str(anatomy)
    assert catalog.unit_id("Anatomiya kafedrasi") == str(anatomy)
    assert catalog.units[str(anatomy)].building == "A bino"
    assert catalog.units[str(rector)].kind == "bolim"
    # Xodimi yo'q turar joy ko'rinmaydi, noma'lum org kaliti — biriktirilmagan.
    assert str(dorm) not in catalog.units
    assert catalog.unit_id(f"org:{uuid.uuid4()}") == svc.UNASSIGNED_KAFEDRA_ID
    assert sorted(catalog.staff_ids(str(anatomy))) == sorted([a, b])
    assert catalog.staff_ids(svc.UNASSIGNED_KAFEDRA_ID) == [d]
    # Bir xil nomli Department alohida qator bo'lib qolmaydi.
    assert [u.name for u in catalog.units.values()].count("Anatomiya kafedrasi") == 1
