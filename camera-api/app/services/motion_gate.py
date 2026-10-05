"""Harakat bo'lmasa tahlil yo'q — kirish kameralarining kuzatuvchilari uchun.

MUAMMO. Kameralar kalit kadrni har soniyada bera boshlagach (2026-09-18,
scripts/camera_stream_settings.py), 11 ta kirish kuzatuvchisi soniyasiga
~11 ta 4K kadrni tahlil qilmoqchi bo'ldi. AVX'siz CPU'da bitta tahlil
~1.3 s: yuz tanish navbati darhol 10/10 band, 17 ta kutmoqda edi. Vaholanki
eshik oldi ko'p vaqt bo'sh — bo'sh eshik kadrida yuz qidirish CPU'ni
odamlar kelgan paytdan tortib oladi.

YECHIM. Kadr 1/8 o'lchamda kulrang holda dekodlanadi (JPEG DCT
masshtablash — to'liq dekodlashdan o'nlab barobar arzon) va oldingi kadr
bilan solishtiriladi. O'zgargan piksellar ulushi chegaradan past bo'lsa,
to'liq tahlil o'tkazib yuboriladi. Xavfsizlik uchun kamida har
`motion_gate_max_skip_seconds` da bir kadr baribir tahlil qilinadi
(yorug'lik asta o'zgarsa yoki odam qimirlamay turgan bo'lsa ham kamera
"ko'r" bo'lib qolmasin).

Taqqoslash eshik hududi (Camera.face_roi) ichida — koridordagi boshqa
harakat (ekran, daraxt soyasi) eshik kadrini tahlilga majburlamasin.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic

import cv2
import numpy as np

from app.config import settings


def small_gray(jpeg_bytes: bytes, roi: tuple[float, float, float, float] | None = None) -> np.ndarray | None:
    """1/8 o'lchamdagi kulrang, biroz xiralashtirilgan kadr (sensor shovqini
    harakat bo'lib ko'rinmasligi uchun). `roi` — normallashgan (x1, y1, x2, y2)."""
    image = cv2.imdecode(np.frombuffer(jpeg_bytes, dtype=np.uint8), cv2.IMREAD_REDUCED_GRAYSCALE_8)
    if image is None or image.size == 0:
        return None
    if roi is not None:
        height, width = image.shape[:2]
        x1, y1, x2, y2 = roi
        crop = image[int(y1 * height) : max(int(y2 * height), int(y1 * height) + 1),
                     int(x1 * width) : max(int(x2 * width), int(x1 * width) + 1)]
        if crop.size:
            image = crop
    return cv2.GaussianBlur(image, (5, 5), 0)


Box = tuple[float, float, float, float]


def motion_box(previous: np.ndarray, current: np.ndarray) -> Box | None:
    """O'zgargan piksellarni o'rab turgan hudud (normallashgan, hoshiyasi
    bilan) yoki None — to'liq kadr tahlil qilinsin.

    Aniqlash vaqti detektorga berilgan piksellar soniga mutanosib
    (productionda 1280 px — 1.7 s, 640 px — 0.43 s). Eshik yoki koridordan
    o'tayotgan odam odatda kadrning kichik qismini egallaydi: faqat shu
    qism tahlil qilinsa, natija bir necha barobar tez keladi, yuz esa
    o'z o'lchamida qoladi (kichraytirilmaydi).

    Bir-ikki piksellik shovqin hududni butun kadrga yoyib yubormasligi uchun
    niqob avval eroziya qilinadi. Hudud juda katta chiqsa (motion_roi_max_area)
    — None: bunday holda to'liq kadr baribir arzonroq."""
    if previous.shape != current.shape:
        return None
    mask = (cv2.absdiff(previous, current) >= settings.motion_gate_pixel_delta).astype(np.uint8)
    eroded = cv2.erode(mask, np.ones((2, 2), np.uint8))
    if np.count_nonzero(eroded):
        mask = eroded
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return None
    height, width = mask.shape
    x1, x2 = float(xs.min()), float(xs.max() + 1)
    y1, y2 = float(ys.min()), float(ys.max() + 1)
    margin = max(0.0, settings.motion_roi_margin)
    pad_x = max((x2 - x1) * margin, width * 0.06)
    pad_y = max((y2 - y1) * margin, height * 0.06)
    x1, x2 = max(0.0, x1 - pad_x) / width, min(float(width), x2 + pad_x) / width
    y1, y2 = max(0.0, y1 - pad_y) / height, min(float(height), y2 + pad_y) / height
    if (x2 - x1) * (y2 - y1) > settings.motion_roi_max_area:
        return None
    return (x1, y1, x2, y2)


def compose_roi(outer: Box | None, inner: Box | None) -> Box | None:
    """`inner` — `outer` hududiga nisbatan normallashgan; natija to'liq
    kadrga nisbatan. Ikkalasidan biri None bo'lsa — ikkinchisi."""
    if inner is None:
        return outer
    if outer is None:
        return inner
    ox1, oy1, ox2, oy2 = outer
    ow, oh = ox2 - ox1, oy2 - oy1
    return (ox1 + inner[0] * ow, oy1 + inner[1] * oh, ox1 + inner[2] * ow, oy1 + inner[3] * oh)


def changed_fraction(previous: np.ndarray, current: np.ndarray) -> float:
    """Sezilarli o'zgargan piksellar ulushi (0..1)."""
    if previous.shape != current.shape:
        return 1.0
    delta = cv2.absdiff(previous, current)
    return float(np.count_nonzero(delta >= settings.motion_gate_pixel_delta)) / delta.size


@dataclass
class MotionGate:
    """Bitta kameraning holati: oldingi kadr va oxirgi to'liq tahlil payti."""

    previous: np.ndarray | None = None
    last_analysed: float = field(default=0.0)
    skipped: int = 0
    # Oxirgi should_analyse() True qaytargan kadrdagi harakat hududi
    # (gate kirishiga — ya'ni `roi` ichiga — nisbatan) yoki None: to'liq kadr.
    region: Box | None = None
    # Kutish paytidagi harakat tekshiruvi (camera_pacing) uchun tayanch.
    _peek_previous: np.ndarray | None = None

    def should_analyse(self, frame: bytes, roi: tuple[float, float, float, float] | None = None) -> bool:
        """Kadrni to'liq tahlil qilish kerakmi. Sinxron (CPU) — chaqiruvchi
        uni event loop'dan tashqarida ishga tushiradi."""
        self.region = None
        if not settings.motion_gate_enabled:
            return True
        current = small_gray(frame, roi)
        if current is None:
            return True  # o'qib bo'lmadi — qaror tahlilning o'ziga qoldiriladi
        previous, self.previous = self.previous, current
        now = monotonic()
        if previous is None or now - self.last_analysed >= settings.motion_gate_max_skip_seconds:
            # Majburiy tahlil — to'liq kadr: qimirlamay turganlar ham ko'rilsin.
            self.last_analysed = now
            return True
        if changed_fraction(previous, current) >= settings.motion_gate_min_changed_fraction:
            self.last_analysed = now
            if settings.motion_roi_enabled:
                self.region = motion_box(previous, current)
            return True
        self.skipped += 1
        return False

    def moved_since_peek(self, frame: bytes, roi: Box | None = None) -> bool:
        """Kutish paytida: kadr oldingi tekshiruvdagidan sezilarli farq
        qiladimi. should_analyse() holatiga tegmaydi."""
        current = small_gray(frame, roi)
        if current is None:
            return False
        previous, self._peek_previous = self._peek_previous, current
        if previous is None:
            return False
        return changed_fraction(previous, current) >= settings.motion_gate_min_changed_fraction

    def reset_peek(self) -> None:
        self._peek_previous = None
