"""2026-09-24 audit tuzatishlari: begona shaxs juftligi, eshik kameralari,
uyqu tekshiruvining behuda burst'i."""

from types import SimpleNamespace

import numpy as np

from app.config import settings
from app.jobs.unauthorized_person_ai import _same_person_pairs
from app.services.camera_roles import is_door_camera


def _unit(*values):
    v = np.asarray(values, dtype=float)
    return v / np.linalg.norm(v)


def _face(*values):
    return SimpleNamespace(embedding=_unit(*values))


class TestStrangerPairing:
    def test_same_person_in_both_frames_is_confirmed(self):
        a = [_face(1, 0, 0)]
        b = [_face(0.95, 0.05, 0)]
        assert _same_person_pairs(a, b) == b

    def test_two_different_strangers_do_not_confirm_each_other(self):
        """Olomonda: 1-kadrda bir notanish, 2-kadrda boshqasi — signal yo'q."""
        assert _same_person_pairs([_face(1, 0, 0)], [_face(0, 1, 0)]) == []

    def test_only_the_repeated_face_is_kept(self):
        repeated, newcomer = _face(0, 0, 1), _face(0, 1, 0)
        assert _same_person_pairs([_face(0, 0.1, 1)], [repeated, newcomer]) == [repeated]


class TestDoorCamera:
    def test_flags_and_room_type(self):
        assert is_door_camera(SimpleNamespace(is_entrance=True, is_exit=False, room_type=None))
        assert is_door_camera(SimpleNamespace(is_entrance=False, is_exit=True, room_type=None))
        assert is_door_camera(SimpleNamespace(is_entrance=False, is_exit=False, room_type="kirish"))
        assert not is_door_camera(SimpleNamespace(is_entrance=False, is_exit=False, room_type="auditoriya"))
