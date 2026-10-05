"""Boshning burilish yo'nalishi — tiriklik tekshiruvining o'lchov qismi.

Bu yerda tarmoq ham, baza ham, model ham qatnashmaydi: faqat landmark
nuqtalaridan yo'nalish chiqarish mantiqi tekshiriladi. Aynan shu joyda
chap va o'ngni almashtirib yuborish oson, va bunday xato hech qanday
xatolik ko'rsatmasdan tekshiruvni teskarisiga aylantirib qo'yardi —
odam chapga bursa tizim "o'ngga burdingiz" deb qabul qilaverardi.
"""

import numpy as np
import pytest

from app.config import settings
from app.services.head_pose import (
    DIRECTION_LABELS,
    direction_of,
    face_height,
    is_close_enough,
    turn_ratio,
)
from app.services.sleep_detection import (
    LEFT_EYE_OUTER_INDEX,
    NOSE_TIP_INDEX,
    RIGHT_EYE_OUTER_INDEX,
)

#: Ko'z tashqi burchaklari TASVIR koordinatasida: odamning o'ng ko'zi
#: tasvirning chap tomonida turadi, ya'ni uning x qiymati kichikroq.
EYE_LEFT_X = 100.0   # odamning O'NG ko'zi — tasvirda chapda
EYE_RIGHT_X = 200.0  # odamning CHAP ko'zi — tasvirda o'ngda
CENTER_X = (EYE_LEFT_X + EYE_RIGHT_X) / 2


def landmarks(nose_x: float) -> np.ndarray:
    a = np.zeros((68, 3))
    a[RIGHT_EYE_OUTER_INDEX][0] = EYE_LEFT_X
    a[LEFT_EYE_OUTER_INDEX][0] = EYE_RIGHT_X
    a[NOSE_TIP_INDEX][0] = nose_x
    return a


def nose_at(ratio: float) -> np.ndarray:
    """turn_ratio aynan `ratio` bo'ladigan landmarklar."""
    span = EYE_RIGHT_X - EYE_LEFT_X
    return landmarks(CENTER_X + ratio * span / 2)


class TestTurnRatio:
    def test_a_centred_nose_reads_as_zero(self):
        assert turn_ratio(landmarks(CENTER_X)) == pytest.approx(0.0, abs=1e-9)

    def test_the_scale_runs_from_minus_one_to_plus_one(self):
        assert turn_ratio(landmarks(EYE_LEFT_X)) == pytest.approx(-1.0)
        assert turn_ratio(landmarks(EYE_RIGHT_X)) == pytest.approx(1.0)

    def test_the_requested_ratio_is_reproduced(self):
        for r in (-0.8, -0.3, 0.0, 0.25, 0.9):
            assert turn_ratio(nose_at(r)) == pytest.approx(r)


class TestDirection:
    def test_a_centred_face_is_front(self):
        assert direction_of(nose_at(0.0)) == "front"

    def test_a_slightly_tilted_face_is_still_front(self):
        """Hech kim boshini ideal to'g'ri ushlab turmaydi. Juda tor
        oraliq odamni bir necha soniya qimirlatib qo'yardi."""
        edge = settings.enrollment_front_tolerance * 0.9
        assert direction_of(nose_at(edge)) == "front"
        assert direction_of(nose_at(-edge)) == "front"

    def test_the_nose_moving_toward_image_right_is_a_turn_to_the_persons_left(self):
        """Odam boshini O'ZINING chap tomoniga bursa, burni tasvirda
        O'NGGA siljiydi. Bu yerda adashish — butun tekshiruvni
        teskarisiga aylantiradi."""
        assert direction_of(nose_at(0.7)) == "left"

    def test_the_nose_moving_toward_image_left_is_a_turn_to_the_persons_right(self):
        assert direction_of(nose_at(-0.7)) == "right"

    def test_a_half_turn_is_neither_accepted_nor_named(self):
        """Yetarli burmagan odam tasdiq olmasligi kerak, aks holda
        tekshiruv bezakka aylanardi. Lekin uni "to'g'ri qaragan" deb ham
        bo'lmaydi — u allaqachon burilgan."""
        between = (settings.enrollment_front_tolerance + settings.enrollment_turn_threshold) / 2
        assert direction_of(nose_at(between)) is None
        assert direction_of(nose_at(-between)) is None

    def test_the_threshold_itself_is_accepted(self):
        assert direction_of(nose_at(settings.enrollment_turn_threshold)) == "left"
        assert direction_of(nose_at(-settings.enrollment_turn_threshold)) == "right"

    def test_the_front_window_is_narrower_than_the_turn_threshold(self):
        """Ikkalasi teng bo'lsa oraliq holat yo'qolib, yarim burilgan
        yuz ham qabul qilinardi."""
        assert settings.enrollment_front_tolerance < settings.enrollment_turn_threshold

    def test_degenerate_geometry_does_not_crash(self):
        """Ko'z burchaklari ustma-ust tushsa (juda kichik yoki buzuq
        aniqlash) frontality_ratio 0,5 qaytaradi — bu "to'g'ri" degani.
        Muhimi: xato tashlanmaydi, chunki bu jonli oqimda har soniyada
        chaqiriladi."""
        a = landmarks(CENTER_X)
        a[RIGHT_EYE_OUTER_INDEX][0] = a[LEFT_EYE_OUTER_INDEX][0] = 150.0
        assert direction_of(a) == "front"


class TestFaceSize:
    def test_a_face_below_the_minimum_is_rejected(self):
        small = settings.enrollment_min_face_height_px - 1
        assert is_close_enough(np.array([0, 0, 50, small])) is False

    def test_a_face_at_the_minimum_is_accepted(self):
        exact = settings.enrollment_min_face_height_px
        assert is_close_enough(np.array([0, 0, 50, exact])) is True

    def test_height_is_measured_in_pixels_not_frame_fraction(self):
        """Talab — ko'z va burun orasidagi haqiqiy piksel aniqligi, va u
        kadr 4K yoki 480p ekanidan o'zgarmaydi."""
        assert face_height(np.array([10, 20, 60, 200])) == 180.0

    def test_the_enrollment_threshold_is_stricter_than_the_sleep_one(self):
        """Bu yerda odam o'z telefonini ushlab turibdi; uxlab qolish
        moduli esa uzoqdagi auditoriya kamerasini ko'radi."""
        assert settings.enrollment_min_face_height_px > settings.sleep_min_face_height_px


class TestLabels:
    def test_every_direction_has_an_uzbek_instruction(self):
        for key in ("front", "left", "right"):
            assert DIRECTION_LABELS[key]

    def test_the_labels_name_the_persons_own_side(self):
        assert "chap" in DIRECTION_LABELS["left"]
        assert "o'ng" in DIRECTION_LABELS["right"]
