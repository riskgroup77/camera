"""Poza backendini tanlash va mediapipe yiqilganda YOLO ga o'tish.

Production serverda protsessor AVX ni qo'llamaydi va mediapipe har
chaqiruvda native SIGILL bilan yiqilardi (~26 marta daqiqasiga). Bu
testlar o'sha holat qaytib kelmasligini qo'riqlaydi — haqiqiy modelsiz,
faqat tanlash mantig'i va COCO -> BlazePose xaritasi.
"""

from concurrent.futures.process import BrokenProcessPool

import numpy as np
import pytest

from app.services import pose_detection as pd

CPUINFO_WITH_AVX = "processor\t: 0\nflags\t\t: fpu sse sse2 ssse3 sse4_1 sse4_2 avx avx2\n"
CPUINFO_WITHOUT_AVX = "processor\t: 0\nflags\t\t: fpu sse sse2 ssse3 sse4_1 sse4_2 popcnt\n"


@pytest.fixture(autouse=True)
def _fresh_module_state(monkeypatch):
    monkeypatch.setattr(pd, "_backend", None)
    monkeypatch.setattr(pd, "_consecutive_crashes", 0)
    monkeypatch.setattr(pd, "_pool", None)


class TestCpuDetection:
    def test_avx_flag_is_found(self):
        assert pd.cpu_supports_avx(CPUINFO_WITH_AVX) is True

    def test_missing_avx_flag_is_reported(self):
        assert pd.cpu_supports_avx(CPUINFO_WITHOUT_AVX) is False

    def test_avx512_alone_is_not_mistaken_for_avx(self):
        """Faqat butun so'z hisoblanadi — "avx512f" satr ichida "avx" bor."""
        assert pd.cpu_supports_avx("flags : sse4_2 avx512f\n") is False

    def test_unreadable_cpuinfo_is_unknown(self):
        assert pd.cpu_supports_avx("") is None


class TestChooseBackend:
    def test_auto_without_avx_uses_yolo(self):
        assert pd.choose_backend("auto", False) == pd.BACKEND_YOLO

    def test_auto_with_avx_uses_mediapipe(self):
        assert pd.choose_backend("auto", True) == pd.BACKEND_MEDIAPIPE

    def test_auto_on_unknown_cpu_keeps_mediapipe(self):
        """Windows/macOS dasturchi mashinasida /proc/cpuinfo yo'q."""
        assert pd.choose_backend("auto", None) == pd.BACKEND_MEDIAPIPE

    @pytest.mark.parametrize("forced", ["mediapipe", "yolo", " YOLO "])
    def test_explicit_choice_wins(self, forced):
        assert pd.choose_backend(forced, False if "mediapipe" in forced else True) == forced.strip().lower()


class TestCocoMapping:
    def _one_person(self):
        xyn = np.zeros((1, 17, 2))
        conf = np.zeros((1, 17))
        for coco_index in range(17):
            xyn[0, coco_index] = (0.01 * (coco_index + 1), 0.02 * (coco_index + 1))
            conf[0, coco_index] = 0.9
        return xyn, conf

    def test_keypoints_land_on_blazepose_indices(self):
        xyn, conf = self._one_person()
        (pose,) = pd.coco_keypoints_to_poses(xyn, conf, np.array([0.8]), max_poses=5)
        assert pose.points.shape == (33, 4)
        # COCO 5 = chap yelka, 11 = chap son, 16 = o'ng to'piq
        assert pose.points[pd.LEFT_SHOULDER][:2] == pytest.approx((0.06, 0.12))
        assert pose.points[pd.LEFT_HIP][:2] == pytest.approx((0.12, 0.24))
        assert pose.points[pd.RIGHT_ANKLE][:2] == pytest.approx((0.17, 0.34))
        assert pose.visible(pd.NOSE, 0.5)

    def test_landmarks_coco_lacks_are_never_visible(self):
        """Ko'z burchagi, barmoq, tovon — COCO da yo'q. Ular 0 ko'rinishda
        qolishi kerak, aks holda iste'molchilar (0,0) nuqtani haqiqiy deb oladi."""
        xyn, conf = self._one_person()
        (pose,) = pd.coco_keypoints_to_poses(xyn, conf, np.array([0.8]), max_poses=5)
        mapped = set(pd.COCO_TO_BLAZEPOSE)
        for index in range(33):
            if index not in mapped:
                assert pose.points[index][3] == 0.0

    def test_most_confident_people_come_first_and_are_capped(self):
        xyn = np.stack([self._one_person()[0][0]] * 3)
        xyn[1] += 0.5  # ajratib olish uchun
        conf = np.full((3, 17), 0.9)
        poses = pd.coco_keypoints_to_poses(xyn, conf, np.array([0.3, 0.95, 0.6]), max_poses=2)
        assert len(poses) == 2
        assert poses[0].points[pd.NOSE][0] == pytest.approx(0.51)

    def test_no_people_gives_no_poses(self):
        assert pd.coco_keypoints_to_poses(np.zeros((0, 17, 2)), np.zeros((0, 17)), np.zeros(0), 5) == []


class TestCrashCircuitBreaker:
    async def test_crashes_below_the_limit_return_no_poses(self, monkeypatch):
        monkeypatch.setattr(pd.settings, "pose_detection_backend", "mediapipe")
        monkeypatch.setattr(pd.settings, "pose_detection_max_worker_crashes", 3)

        async def crash(_):
            raise BrokenProcessPool("SIGILL")

        monkeypatch.setattr(pd, "_run_mediapipe_worker", crash)
        monkeypatch.setattr(pd, "_detect_yolo_sync", lambda _: pytest.fail("YOLO chaqirilmasligi kerak"))

        assert await pd.detect_poses(b"frame") == []
        assert await pd.detect_poses(b"frame") == []
        assert pd.active_pose_backend() == pd.BACKEND_MEDIAPIPE

    async def test_repeated_crashes_switch_to_yolo_for_good(self, monkeypatch):
        monkeypatch.setattr(pd.settings, "pose_detection_backend", "mediapipe")
        monkeypatch.setattr(pd.settings, "pose_detection_max_worker_crashes", 3)
        worker_calls = []

        async def crash(_):
            worker_calls.append(1)
            raise BrokenProcessPool("SIGILL")

        sentinel = [pd.PoseLandmarks(points=np.zeros((33, 4)))]
        monkeypatch.setattr(pd, "_run_mediapipe_worker", crash)
        monkeypatch.setattr(pd, "_detect_yolo_sync", lambda _: sentinel)

        await pd.detect_poses(b"frame")
        await pd.detect_poses(b"frame")
        assert await pd.detect_poses(b"frame") is sentinel  # uchinchisi — o'tish
        assert pd.active_pose_backend() == pd.BACKEND_YOLO

        # Endi mediapipe ishchisi umuman qayta tug'dirilmaydi
        assert await pd.detect_poses(b"frame") is sentinel
        assert len(worker_calls) == 3

    async def test_a_success_resets_the_crash_count(self, monkeypatch):
        monkeypatch.setattr(pd.settings, "pose_detection_backend", "mediapipe")
        monkeypatch.setattr(pd.settings, "pose_detection_max_worker_crashes", 2)
        outcomes = iter(["crash", "ok", "crash", "ok"])

        async def flaky(_):
            if next(outcomes) == "crash":
                raise BrokenProcessPool("SIGILL")
            return []

        monkeypatch.setattr(pd, "_run_mediapipe_worker", flaky)
        for _ in range(4):
            await pd.detect_poses(b"frame")
        assert pd.active_pose_backend() == pd.BACKEND_MEDIAPIPE

    async def test_auto_without_avx_never_starts_mediapipe(self, monkeypatch):
        monkeypatch.setattr(pd.settings, "pose_detection_backend", "auto")
        monkeypatch.setattr(pd, "cpu_supports_avx", lambda *a: False)

        async def must_not_run(_):
            pytest.fail("AVX yo'q protsessorda mediapipe ishga tushmasligi kerak")

        monkeypatch.setattr(pd, "_run_mediapipe_worker", must_not_run)
        monkeypatch.setattr(pd, "_detect_yolo_sync", lambda _: [])
        assert await pd.detect_poses(b"frame") == []
        assert pd.active_pose_backend() == pd.BACKEND_YOLO


def test_yolo_backend_rejects_undecodable_bytes_without_loading_the_model(monkeypatch):
    monkeypatch.setattr(pd, "_get_yolo_model", lambda: pytest.fail("model yuklanmasligi kerak"))
    assert pd._detect_yolo_sync(b"not a real image") == []
    assert pd._detect_yolo_sync(b"") == []
