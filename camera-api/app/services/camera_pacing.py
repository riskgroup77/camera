"""Hisoblash kuchini yuz ko'rayotgan kameralarga yo'naltirish.

Productionda (2026-09-24, 07:00-10:40) 107 ta kamera kuzatuvchisi AI
slotlarini TENG bo'lishardi: har kamera ~60 s da bir kadr. Holbuki 50 ga
yaqin kamera kun bo'yi birorta ham tahlilga yaroqli yuz bermadi (bo'sh
koridor, orqa tomondan ko'radigan burchak), yuzlar esa 15 ta kamerada
to'planardi. Tahlil vaqtining yarmi hech narsa bermaydigan kadrlarga
ketardi.

Endi har kamera o'z "hosildorligi" bo'yicha ishlaydi:
  * yaroqli yuz (tahlil o'lchamidagi yoki zoom orqali olingan) ko'rgan
    kamera — darhol keyingi kadr;
  * ketma-ket `pacing_idle_after` kadrda yaroqli yuz bo'lmasa — keyingi
    kadrdan oldin kutadi, har bo'sh kadrda ikki baravar ko'proq
    (`pacing_idle_base_seconds` .. `pacing_idle_max_seconds`);
  * birinchi yaroqli yuzning o'zidayoq navbat tiklanadi.

Kirish/chiqish kameralari hech qachon kutmaydi — odam eshikdan 2-3 s da
o'tadi va boshqa joyda ko'rinmasligi mumkin."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import settings


@dataclass
class CameraPacer:
    exempt: bool = False
    empty_streak: int = 0

    def note(self, useful_faces: int) -> float:
        """Kadr natijasini qayd etadi; keyingi kadrdan oldin necha soniya
        kutishni qaytaradi (0 — kutmaydi)."""
        if useful_faces > 0:
            self.empty_streak = 0
            return 0.0
        self.empty_streak += 1
        if self.exempt or not settings.pacing_enabled:
            return 0.0
        over = self.empty_streak - settings.pacing_idle_after
        if over < 0:
            return 0.0
        base = max(0.0, settings.pacing_idle_base_seconds)
        return min(settings.pacing_idle_max_seconds, base * (2 ** min(over, 10)))
