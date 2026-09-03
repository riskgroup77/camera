"""_path_config decides how MediaMTX serves every camera to the browser —
plain RTSP relay, or a per-camera live libx264 transcode. It had no test
coverage at all, while a wrong flag here is what put the production wall
2-3 minutes behind live: a live encoder that can't keep up doesn't drop
frames, it falls further behind every second.

Measured on production before these tests were written: substreams are
HEVC at 640x360 and 768x432, and the transcode was configured to scale
everything to 720p — upscaling, i.e. paying several times the pixel cost
for detail that cannot exist."""

import pytest

from app.config import settings
from app.services.video_gateway import _path_config

RTSP = "rtsp://user:pw@10.0.0.5:554/Streaming/Channels/102"


@pytest.fixture(autouse=True)
def _transcode_mode(monkeypatch):
    """Default these tests to the production shape: transcode enabled."""
    monkeypatch.setattr(settings, "mediamtx_relay_h264_substream", False)
    monkeypatch.setattr(settings, "mediamtx_transcode_h264", True)


class TestRelayMode:
    def test_relay_flag_gives_a_plain_source_with_no_encoder(self, monkeypatch):
        monkeypatch.setattr(settings, "mediamtx_relay_h264_substream", True)
        config = _path_config(RTSP)
        assert config["source"] == RTSP
        assert "runOnDemand" not in config  # no ffmpeg, no encoder, no drift

    def test_transcode_disabled_also_relays(self, monkeypatch):
        monkeypatch.setattr(settings, "mediamtx_transcode_h264", False)
        config = _path_config(RTSP)
        assert config["source"] == RTSP
        assert "runOnDemand" not in config


class TestTranscodeMode:
    def test_no_scale_filter_when_height_is_zero(self, monkeypatch):
        """Substreams are already small and come in mixed sizes; ANY fixed
        height upscales part of the fleet. Zero means "leave it alone"."""
        monkeypatch.setattr(settings, "mediamtx_transcode_height", 0)
        cmd = _path_config(RTSP)["runOnDemand"]
        assert "-vf scale" not in cmd

    def test_scale_filter_present_when_height_is_set(self, monkeypatch):
        monkeypatch.setattr(settings, "mediamtx_transcode_height", 360)
        cmd = _path_config(RTSP)["runOnDemand"]
        assert "-vf scale=-2:360" in cmd

    def test_framerate_cap_is_omitted_when_zero(self, monkeypatch):
        monkeypatch.setattr(settings, "mediamtx_transcode_fps", 0)
        cmd = _path_config(RTSP)["runOnDemand"]
        assert " -r " not in cmd

    def test_framerate_cap_is_applied_when_set(self, monkeypatch):
        monkeypatch.setattr(settings, "mediamtx_transcode_fps", 12)
        cmd = _path_config(RTSP)["runOnDemand"]
        assert "-r 12" in cmd

    def test_close_after_follows_the_setting(self, monkeypatch):
        monkeypatch.setattr(settings, "mediamtx_transcode_close_after_seconds", 15)
        assert _path_config(RTSP)["runOnDemandCloseAfter"] == "15s"

    def test_credentials_in_the_url_are_shell_quoted(self):
        """The RTSP URL carries camera credentials and goes into a command
        string MediaMTX executes — an unquoted special character would
        break the command or worse."""
        tricky = "rtsp://user:p$w;rm -rf@10.0.0.5:554/x"
        cmd = _path_config(tricky)["runOnDemand"]
        assert "rm -rf@10.0.0.5" not in cmd.replace("'", "")[len("/ffmpeg") :].split(" -i ")[0]
        assert "'" in cmd  # shlex.quote wrapped it

    def test_audio_is_dropped(self):
        """Nothing in this product plays camera audio; encoding it would be
        pure waste on a CPU-bound box."""
        assert "-an" in _path_config(RTSP)["runOnDemand"]
