"""Sanoqlar ustma-ust tushmaydi: "Yuzi bazada yo'q" — yuzi yo'q VA yozuvi yo'q.

2026-10-06: talabalar sanog'ida "Keldi 1412" ning ~1100 tasi HEMIS bo'yicha
kelgan yuzsizlar edi va ular "Yuzi bazada yo'q 5091" da ham sanalardi —
raqamlar jamiga qo'shilmasdi."""

from app.services.situation import Counts


def test_no_face_is_only_the_faceless_without_any_record():
    counts = Counts()
    counts.add(False, "keldi", 1096, pending=True)  # HEMIS: kelgan, yuzi yo'q
    counts.add(False, "kelmadi", 18, pending=True)
    counts.add(True, "keldi", 299, pending=True)
    counts.add(True, None, 1849, pending=True)  # yuzi bor, hali kelmagan
    counts.add(False, None, 3997, pending=True)  # yuzi ham, ma'lumoti ham yo'q
    assert (counts.present, counts.absent, counts.not_yet, counts.no_face) == (1395, 18, 1849, 3997)
    no_data_with_face = counts.no_data - counts.no_face
    assert counts.present + counts.absent + counts.not_yet + no_data_with_face + counts.no_face == counts.total == 7259


def test_past_day_enrolled_without_record_is_no_data_not_faceless():
    counts = Counts()
    counts.add(True, None, 807, pending=False)
    counts.add(False, None, 1317, pending=False)
    assert counts.no_data == 2124 and counts.no_face == 1317
    assert counts.merge(Counts(no_face=3)).no_face == 1320
    assert counts.out().no_face == 1320
