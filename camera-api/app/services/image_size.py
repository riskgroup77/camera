"""Read a JPEG's pixel dimensions from its header, without decoding it.

Two call sites needed only the width/height of a frame and were paying a
FULL cv2.imdecode for it — app/routers/public.py's live-detection endpoint
(on every poll, on the event loop) and app/jobs/unauthorized_person_ai.py's
face-size filter (a SECOND decode of a frame detect_faces had already
decoded). At 2560x1440 that is real CPU per call, and in the router's case
it ran synchronously inside an async handler, stalling every other request
on that worker.

Parsing the header instead is O(number of segments) over a few hundred
bytes: no pixel data is touched, so there is nothing worth pushing to a
thread either. Frames here come from ffmpeg's MJPEG output (baseline
SOF0), but every SOF variant carries dimensions in the same place, so all
of them are handled.
"""

# Start-of-frame markers carry the dimensions. C4 (DHT), C8 (JPG) and CC
# (DAC) sit in the same numeric range but are NOT frame headers.
_SOF_MARKERS = frozenset(
    [0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF]
)


def jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    """Returns (width, height), or None if `data` isn't a JPEG this can
    read — callers must treat None as "unknown" and fail open rather than
    guessing, since a wrong size is worse than no size."""
    if len(data) < 4 or data[0] != 0xFF or data[1] != 0xD8:
        return None

    i = 2
    end = len(data)
    while i + 3 < end:
        if data[i] != 0xFF:
            # Not aligned on a marker — resynchronise rather than give up:
            # a truncated/padded MJPEG frame can carry fill bytes here.
            i += 1
            continue
        marker = data[i + 1]
        if marker == 0xFF:  # fill byte, marker follows
            i += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:  # standalone, no length
            i += 2
            continue
        if marker == 0xD9:  # end of image
            return None
        segment_length = (data[i + 2] << 8) | data[i + 3]
        if segment_length < 2:
            return None  # malformed: length includes its own 2 bytes
        if marker in _SOF_MARKERS:
            # SOF payload: precision(1) height(2) width(2)
            if i + 9 >= end:
                return None
            height = (data[i + 5] << 8) | data[i + 6]
            width = (data[i + 7] << 8) | data[i + 8]
            if width <= 0 or height <= 0:
                return None
            return width, height
        i += 2 + segment_length

    return None


def jpeg_height(data: bytes) -> int:
    """Height in pixels, or 0 when it can't be determined — 0 is the
    "unknown" signal callers already treat as fail-open."""
    dims = jpeg_dimensions(data)
    return dims[1] if dims else 0
