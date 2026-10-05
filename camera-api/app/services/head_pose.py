"""Boshning burilish yo'nalishi — biometrik ro'yxatdan o'tishdagi tiriklik
tekshiruvi uchun.

NIMA UCHUN KERAK. Tayyor rasm yuklash zaif dalil: uni boshqa odamning
rasmi bilan, telefon ekranidagi surat bilan yoki qog'ozga bosilgan fotosurat
bilan almashtirib bo'ladi. Odamdan boshini burishni so'rash bu hujumlarning
katta qismini yopadi: statik rasm burilmaydi, va uch xil burchakdagi kadr
bir xil odamniki ekanligi alohida tekshiriladi.

USUL. Alohida poza modeli YUKLANMAYDI. InsightFace har bir aniqlashda
allaqachon 68 nuqtali landmark beradi, va app/services/sleep_detection.py
o'sha nuqtalardan `frontality_ratio` ni hisoblaydi:

    ratio = (burun_x - o'ng_ko'z_tashqi_x) / (chap_ko'z_tashqi_x - o'ng_ko'z_tashqi_x)

Bu qiymat to'g'ri qaragan yuzda ~0,5 bo'ladi va bosh burilgan sari 0 yoki 1
tomon siljiydi. Ya'ni bizga kerakli ma'lumot allaqachon hisoblangan — faqat
uni yo'nalishga aylantirish qoldi.

KOORDINATA IZOHI (bu yerda adashish oson). Nuqtalar TASVIR koordinatasida.
Odamning O'NG ko'zi tasvirning CHAP tomonida turadi. Odam boshini O'ZINING
chap tomoniga bursa, burni tasvirda O'NGGA siljiydi va ratio 0,5 dan
KATTA bo'ladi.

MIRRORING. Brauzerdagi ko'rinish oyna kabi teskari ko'rsatiladi (odam
o'zini tabiiy ko'rishi uchun), lekin serverga YUBORILADIGAN kadr teskari
qilinmaydi. Aks holda chap va o'ng joy almashib qolardi.
"""

from __future__ import annotations

from typing import Literal

import numpy as np

from app.config import settings
from app.services.sleep_detection import frontality_ratio

Direction = Literal["front", "left", "right"]

#: Foydalanuvchiga ko'rsatiladigan nomlar.
DIRECTION_LABELS: dict[str, str] = {
    "front": "to'g'riga qarang",
    "left": "boshingizni chapga buring",
    "right": "boshingizni o'ngga buring",
}

_CENTER = 0.5

#: Chegarani solishtirishdagi suzuvchi nuqta bo'shligi.
#:
#: Chegaraga AYNAN teng qiymat qabul qilinishi kerak, lekin 0,34 ni
#: nuqtalardan qayta hisoblaganda 0,33999999999999997 chiqishi mumkin.
#: Bunday farq o'lchov emas, ikkilik sanoq tizimining qoldig'i — va u
#: odamning boshi yetarli burilganini yo'qqa chiqarmasligi kerak.
_EPS = 1e-9


def turn_ratio(landmarks_68: np.ndarray) -> float:
    """-1 dan +1 gacha: manfiy — o'ngga burilgan, musbat — chapga.

    frontality_ratio (0..1, markazi 0,5) ni markazi nolda bo'lgan va
    o'qilishi oson shkalaga o'tkazadi."""
    return float((frontality_ratio(landmarks_68) - _CENTER) * 2.0)


def direction_of(landmarks_68: np.ndarray) -> Direction | None:
    """Yuz qaysi tomonga burilgan. None — oraliq holat.

    Oraliq holat ataylab alohida: bosh biroz burilgan, lekin na to'g'ri,
    na yetarlicha burilgan. Bunday kadrni «to'g'ri» deb qabul qilish
    tiriklik tekshiruvini bo'shashtirardi, «burilgan» deb qabul qilish esa
    odamni aldab qo'yardi — u yetarli burmagan bo'lsa ham tasdiq olardi.
    """
    ratio = turn_ratio(landmarks_68)
    if abs(ratio) <= settings.enrollment_front_tolerance + _EPS:
        return "front"
    if ratio >= settings.enrollment_turn_threshold - _EPS:
        return "left"
    if ratio <= -settings.enrollment_turn_threshold + _EPS:
        return "right"
    return None


def face_height(bbox) -> float:
    return float(bbox[3] - bbox[1])


def is_close_enough(bbox) -> bool:
    """Yuz o'lchov uchun yetarlicha kattami.

    Kichik yuzda landmark nuqtalari bir necha piksel farq bilan
    joylashadi va burilish burchagi shovqindan ajralmay qoladi. Bu
    app/services/sleep_detection.py'dagi is_face_measurable bilan bir xil
    mulohaza, faqat chegara yuqoriroq: u yerda kamera uzoqdagi odamni
    ko'radi, bu yerda esa odam o'z telefonini ushlab turibdi."""
    return face_height(bbox) >= settings.enrollment_min_face_height_px
