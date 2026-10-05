"""scripts/probe_camera_streams.py — ffprobe paket ro'yxatini o'qish.

2026-09-18 da serverda skript `float('N/A')` dan yiqildi: ba'zi kameralar
paket vaqtini bermaydi."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "probe_camera_streams.py"


@pytest.fixture(scope="module")
def probe():
    spec = importlib.util.spec_from_file_location("probe_camera_streams", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_timed_keyframes_give_the_interval(probe):
    text = "0.000,0.000,K__\n0.040,0.040,___\n2.000,2.000,K__\n4.000,4.000,K__\n"
    packets, keyframes, untimed = probe.parse_packets(text)
    assert (packets, keyframes, untimed) == (4, [0.0, 2.0, 4.0], 0)
    assert probe.keyframe_interval(keyframes, untimed) == 2.0


def test_missing_pts_falls_back_to_dts(probe):
    packets, keyframes, untimed = probe.parse_packets("N/A,1.500,K__\nN/A,1.540,___\nN/A,3.500,K__\n")
    assert (packets, keyframes, untimed) == (3, [1.5, 3.5], 0)


def test_no_timestamps_at_all_are_counted_not_crashed(probe):
    packets, keyframes, untimed = probe.parse_packets("N/A,N/A,K__\nN/A,N/A,___\nN/A,N/A,K__\nN/A,N/A,K__\n")
    assert (packets, keyframes, untimed) == (4, [], 3)
    assert probe.keyframe_interval(keyframes, untimed) == round(probe.READ_SECONDS / 3, 2)


def test_a_single_keyframe_has_no_interval(probe):
    assert probe.keyframe_interval([], 1) is None
    assert probe.keyframe_interval([5.0], 0) is None
