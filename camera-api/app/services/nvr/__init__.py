"""NVR yozuvlari — kunlik video tahlil manbai (docs/KUNLIK_VIDEO_TAHLIL.md)."""

from app.services.nvr.isapi import IsapiClient, NvrChannel, NvrError, RecordingSpan
from app.services.nvr.sources import Frame, PlaybackSource, VideoReadError, isapi_for, source_for

__all__ = [
    "Frame",
    "IsapiClient",
    "NvrChannel",
    "NvrError",
    "PlaybackSource",
    "RecordingSpan",
    "VideoReadError",
    "isapi_for",
    "source_for",
]
