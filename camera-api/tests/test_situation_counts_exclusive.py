"""Sanoqlar ustma-ust tushmaydi (buyurtmachi qarori, 2026-10-06).

"Yuzi bazada yo'q" — yuzi bazada yo'q odamlarning HAMMASI (har kuni bir xil
son); keldi / kelmadi / hali kelmagan / ma'lumot yo'q — faqat yuzi borlar
orasida. Ilgari HEMIS bo'yicha kelgan yuzsizlar "Keldi"da ham, "Yuzsiz"da ham
sanalib, raqamlar jamiga qo'shilmasdi."""

from app.services.situation import Counts


def _day(pending: bool) -> Counts:
    counts = Counts()
    counts.add(False, "keldi", 1096, pending=pending)  # HEMIS: kelgan, yuzi yo'q
    counts.add(False, "kelmadi", 18, pending=pending)
    counts.add(False, None, 3997, pending=pending)
    counts.add(True, "keldi", 299, pending=pending)
    counts.add(True, "kech_keldi", 18, pending=pending)
    counts.add(True, "kelmadi", 2, pending=pending)
    counts.add(True, None, 1849, pending=pending)
    return counts


def test_faceless_people_are_only_counted_as_faceless():
    today = _day(pending=True)
    assert (today.present, today.late, today.absent, today.not_yet) == (317, 18, 2, 1849)
    assert today.no_face == 1096 + 18 + 3997 == today.total - today.enrolled
    with_face_no_data = today.no_data - today.no_face
    assert today.present + today.absent + today.not_yet + with_face_no_data + today.no_face == today.total


def test_faceless_count_is_the_same_on_every_day():
    today, past = _day(pending=True), _day(pending=False)
    assert today.no_face == past.no_face
    # O'tgan kunda yuzi bor, yozuvsiz — "Ma'lumot yo'q" (yuzsiz emas).
    assert past.not_yet == 0 and past.no_data - past.no_face == 1849
    assert past.rate == round(317 * 100 / (317 + 2), 1)


def test_merge_and_output_keep_no_face():
    merged = Counts(no_face=5).merge(Counts(no_face=3))
    assert merged.no_face == 8 and merged.out().no_face == 8
