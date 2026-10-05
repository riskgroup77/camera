"""app/services/thread_limits.py — hisoblash kutubxonalarining oqimlari."""

import cv2
import pytest

from app.config import settings
from app.services import thread_limits


def test_defaults_leave_libraries_alone(monkeypatch):
    monkeypatch.setattr(settings, "ai_torch_threads", 0)
    monkeypatch.setattr(settings, "cv_internal_threads", -1)
    assert thread_limits.apply_thread_limits() == {"torch": None, "opencv": None}


def test_limits_are_applied(monkeypatch):
    torch = pytest.importorskip("torch")
    before_torch, before_cv = torch.get_num_threads(), cv2.getNumThreads()
    monkeypatch.setattr(settings, "ai_torch_threads", 1)
    monkeypatch.setattr(settings, "cv_internal_threads", 1)
    try:
        assert thread_limits.apply_thread_limits() == {"torch": 1, "opencv": 1}
    finally:
        torch.set_num_threads(before_torch)
        cv2.setNumThreads(before_cv)
