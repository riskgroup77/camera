"""PWA ikonlarini yaratish (public/icons/). Qayta yaratish:

    camera-api/.venv/Scripts/python scripts/generate_pwa_icons.py public/icons

opencv-python-headless (camera-api/requirements.txt) yetarli; Pillow kerak emas.
Indigo fon + oq "kamera ko'zi" (linza) belgisi.
"""
import sys
from pathlib import Path

import cv2
import numpy as np

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
SS = 4  # supersampling

TOP = np.array([0x63, 0x66, 0xF1], dtype=np.float32)  # indigo-500 (RGB)
BOTTOM = np.array([0x43, 0x38, 0xCA], dtype=np.float32)  # indigo-700
WHITE = (255, 255, 255)


def render(size: int, *, rounded: bool, content_scale: float) -> np.ndarray:
    n = size * SS
    t = np.linspace(0, 1, n, dtype=np.float32)[:, None, None]
    rgb = TOP * (1 - t) + BOTTOM * t
    img = np.repeat(rgb, n, axis=1).astype(np.uint8)  # (n, n, 3) RGB
    alpha = np.full((n, n), 255, np.uint8)
    if rounded:
        alpha[:] = 0
        r = int(n * 0.22)
        cv2.rectangle(alpha, (r, 0), (n - r - 1, n - 1), 255, -1, cv2.LINE_AA)
        cv2.rectangle(alpha, (0, r), (n - 1, n - r - 1), 255, -1, cv2.LINE_AA)
        for cx, cy in ((r, r), (n - r - 1, r), (r, n - r - 1), (n - r - 1, n - r - 1)):
            cv2.circle(alpha, (cx, cy), r, 255, -1, cv2.LINE_AA)

    c = n // 2
    unit = n * content_scale / 2  # belgi radiusi
    # Ko'z (bodom shakli): ikki yoy — ellips konturi.
    eye_w, eye_h = int(unit * 0.98), int(unit * 0.62)
    thick = max(2, int(unit * 0.11))
    cv2.ellipse(img, (c, c), (eye_w, eye_h), 0, 0, 360, WHITE, thick, cv2.LINE_AA)
    # Linza: halqa + markaz.
    cv2.circle(img, (c, c), int(unit * 0.42), WHITE, thick, cv2.LINE_AA)
    cv2.circle(img, (c, c), int(unit * 0.2), WHITE, -1, cv2.LINE_AA)
    # Yozuv nuqtasi (REC) — yuqori o'ngda.
    cv2.circle(img, (c + int(unit * 0.72), c - int(unit * 0.72)), int(unit * 0.12), (0xF8, 0x71, 0x71), -1, cv2.LINE_AA)

    rgba = np.dstack([img, alpha])
    small = cv2.resize(rgba, (size, size), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_RGBA2BGRA)


def save(name: str, arr: np.ndarray) -> None:
    ok, buf = cv2.imencode(".png", arr, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    assert ok
    (OUT / name).write_bytes(buf.tobytes())
    print(name, arr.shape, len(buf))


save("icon-192.png", render(192, rounded=True, content_scale=0.78))
save("icon-512.png", render(512, rounded=True, content_scale=0.78))
# Maskable: to'liq fon, belgi markaziy 80% "xavfsiz zona" ichida.
save("icon-maskable-192.png", render(192, rounded=False, content_scale=0.6))
save("icon-maskable-512.png", render(512, rounded=False, content_scale=0.6))
# iOS o'zi burchaklarni yumaloqlaydi.
save("apple-touch-icon.png", render(180, rounded=False, content_scale=0.66))
