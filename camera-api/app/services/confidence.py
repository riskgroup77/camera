"""Detektor o'lchovidan hisoblangan ishonch (0-100).

Ilgari ko'p modul doimiy qiymat yuborardi (35, 40, 55, 65, 70, 85) —
"bu evristika taxminan shunchalik ishonchli" degan o'z-o'zini baholash,
o'lchov emas. Natijada modul chegarasi (AIModuleConfig.threshold) faqat
yoqish/o'chirish tugmasi edi: chegara doimiydan past bo'lsa hamma signal
o'tardi, yuqori bo'lsa birortasi ham.

Endi ishonch har bir signalning O'Z o'lchovidan chiqadi: harakat chegaradan
necha barobar oshdi, bilak og'izga qanchalik yaqin, oq rang ulushi
chegaradan qanchalik past, yuz ro'yxatdagi eng yaqin odamdan qanchalik uzoq.

QOIDA — `floor`. Detektor o'z chegarasidan ENDIGINA o'tgan signal `floor`
oladi; u modulning standart chegarasiga teng tanlangan. Shu tufayli bu
o'zgarish bilan hech bir signal jimgina yo'qolib qolmaydi, admin esa
chegarani ko'tarib, faqat kuchliroq signallarni qoldira oladi — chegara
endi haqiqiy sezgirlik dastagi.
"""

from __future__ import annotations


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def exceed_confidence(value: float, threshold: float, *, floor: int, ceiling: int = 95, full_at: float = 2.0) -> int:
    """Kattaroq qiymat — kuchliroq signal (harakat kattaligi, niqob rangi).

    value == threshold -> floor; value >= threshold * full_at -> ceiling."""
    if threshold <= 0:
        return floor
    ratio = value / threshold
    if ratio <= 1:
        return floor
    progress = _clamp((ratio - 1) / max(full_at - 1, 1e-6), 0.0, 1.0)
    return int(round(floor + (ceiling - floor) * progress))


def below_confidence(value: float, threshold: float, *, floor: int, ceiling: int = 95) -> int:
    """Kichikroq qiymat — kuchliroq signal (bilak-og'iz masofasi, oq rang ulushi).

    value == threshold -> floor; value == 0 -> ceiling."""
    if threshold <= 0:
        return floor
    progress = _clamp((threshold - value) / threshold, 0.0, 1.0)
    return int(round(floor + (ceiling - floor) * progress))


def weakest(*scores: int | None, default: int) -> int:
    """Ikki kadrli tasdiqlash: signal eng zaif kadr qadar ishonchli."""
    present = [s for s in scores if s is not None]
    return min(present) if present else default
