"""app/services/live_clock.py — skaner ramkasini video kadriga moslash."""

import numpy as np

from app.services import live_clock
from app.services.live_clock import ClockCalibrator, best_match_time, parse_media_playlist


def _scene(person_x: int | None) -> np.ndarray:
    image = np.full((90, 160), 80.0, dtype=np.float32)
    if person_x is not None:
        image[30:70, person_x : person_x + 12] = 220.0
    return image


def test_playlist_times_are_carried_between_date_tags():
    init, segments = parse_media_playlist(
        "#EXTM3U\n#EXT-X-MAP:URI=\"init.mp4\"\n#EXTINF:1.92,\nseg0.mp4\n"
        "#EXT-X-PROGRAM-DATE-TIME:2026-09-24T13:16:25.500Z\n#EXTINF:2.0,\nseg1.mp4\n#EXTINF:1.5,\nseg2.mp4\n"
    )
    assert init == "init.mp4"
    # seg0 vaqt belgisidan oldin — vaqti noma'lum, tashlanadi.
    assert [s.uri for s in segments] == ["seg1.mp4", "seg2.mp4"]
    assert segments[1].start - segments[0].start == 2.0


def test_the_frame_where_the_person_stands_is_found():
    frames = [(100.0 + i * 0.1, _scene(10 + i * 10)) for i in range(12)]
    # AI kadrida odam x=60 da — HLS da bu 5-kadr (100.5 s).
    assert best_match_time(_scene(60), frames) == 100.5


def test_a_still_scene_gives_no_measurement():
    frames = [(100.0 + i * 0.1, _scene(None)) for i in range(12)]
    assert best_match_time(_scene(None), frames) is None


async def test_calibrator_smooths_and_ignores_empty_measurements(monkeypatch):
    results = iter([1.0, None, 2.0])

    async def fake_measure(url, frame, captured):
        return next(results)

    monkeypatch.setattr(live_clock, "measure_offset", fake_measure)
    calibrator = ClockCalibrator(interval=0.0)
    for _ in range(3):
        calibrator.maybe_measure("cam", "http://hls", b"jpg", 10.0)
        await calibrator._running["cam"]
    # 1000 -> (bo'sh o'lchov e'tiborsiz) -> 0.6*1000 + 0.4*2000
    assert calibrator.offset_ms("cam") == 1400
    assert calibrator.offset_ms("other") is None


async def test_clock_is_measured_only_for_hls_viewers():
    from app.services import live_focus

    await live_focus.mark_focus("webrtc-cam")
    await live_focus.mark_focus("hls-cam", hls=True)
    assert await live_focus.is_focused("webrtc-cam") and await live_focus.is_focused("hls-cam")
    assert not await live_focus.watched_over_hls("webrtc-cam")
    assert await live_focus.watched_over_hls("hls-cam")
