"""TT kriteriya 11 ("Bosh kiyim (kalpakcha) borligi") — klassik rang
bir xillik tahliliga asoslangan TAXMINIY aniqlash, chuqur o'qitilgan
model EMAS. app/services/coat_detection.py'ning "honest scope" izohi
bu yerga ham tegishli — 6 ta studiya fotosi (oq, qizil, ko'k kalpokchalar)
haqiqiy klassifikator o'qitish uchun yetarli emas.

Kalpakcha istalgan rangda bo'lishi mumkinligi sababli (yuborilgan
namunalarda oq, qizil, ko'k — aniq bitta rang yo'q), bu yerda muayyan
rangni emas, balki BOSH TEPASI hududining rang BIR XILLIGINI (uniformity)
tekshiramiz: sochsiz, silliq mato yuzasi (kalpakcha) odatda och sochga
qaraganda ancha bir tekis rangda bo'ladi, soch esa yorug'lik/soya va
tola tuzilishi tufayli ko'proq rang tarqalishiga (varianceга) ega.

Hudud mediapipe pose'ning quloq landmarklaridan (kenglik mos yozuvi
sifatida) va burun landmarkidan (vertikal mos yozuv sifatida)
geometrik taxmin qilinadi — mediapipe'da alohida "bosh tepasi"
landmarki yo'q.

Bilib turilgan cheklovlar: juda bir tekis rangli qisqa sochlar
(masalan silliq qora soch) xato ijobiy berishi mumkin; murakkab
turmakli/rangli sochlar xato salbiy berishi mumkin. Haqiqiy institut
kamerasi kadri bilan hali sinovdan o'tkazilmagan — faqat sintetik test
koordinatalarida tekshirilgan (tests/test_head_covering_detection.py)."""

import cv2
import numpy as np

from app.config import settings
from app.services.pose_detection import LEFT_EAR, NOSE, RIGHT_EAR


def head_top_bbox(points: np.ndarray, frame_width: int, frame_height: int) -> tuple[int, int, int, int] | None:
    """Bosh tepasi (peshonadan yuqori, sochning tepa qismi) hududining
    piksel-fazodagi (x1, y1, x2, y2) chegarasi. Quloq/burun landmarklari
    yetarlicha ko'rinmasa None."""
    required = [LEFT_EAR, RIGHT_EAR, NOSE]
    if not all(points[i][3] >= settings.head_covering_min_landmark_visibility for i in required):
        return None

    ear_dx = points[RIGHT_EAR][0] - points[LEFT_EAR][0]
    ear_width = abs(float(ear_dx))
    if ear_width <= 1e-4:
        return None
    center_x = (points[LEFT_EAR][0] + points[RIGHT_EAR][0]) / 2
    nose_y = float(points[NOSE][1])

    x1 = max(0.0, center_x - ear_width * settings.head_covering_width_factor)
    x2 = min(1.0, center_x + ear_width * settings.head_covering_width_factor)
    y1 = max(0.0, nose_y - ear_width * settings.head_covering_height_factor)
    y2 = max(0.0, nose_y - ear_width * settings.head_covering_top_margin_factor)

    px1, py1 = int(x1 * frame_width), int(y1 * frame_height)
    px2, py2 = int(x2 * frame_width), int(y2 * frame_height)
    if px2 <= px1 or py2 <= py1:
        return None
    return px1, py1, px2, py2


def color_uniformity(image: np.ndarray, bbox: tuple[int, int, int, int]) -> float:
    """bbox ichidagi rang bir xilligi — 0 (juda xilma-xil) dan 1 (bir
    tekis) gacha. HSV Hue va Saturation kanallarining standart
    og'ishidan hisoblanadi (past og'ish = bir tekis yuza)."""
    x1, y1, x2, y2 = bbox
    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        return 0.0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV).astype(np.float32)
    hue_std = float(np.std(hsv[:, :, 0]))
    sat_std = float(np.std(hsv[:, :, 1]))
    # Normalizatsiya: taxminan "juda xilma-xil" qiymatlarga qarab tanlangan
    # doiralar (Hue 0-180, Saturation 0-255 OpenCV'da) — kalibrlanishi mumkin.
    combined_spread = (hue_std / 60.0) + (sat_std / 80.0)
    return max(0.0, 1.0 - combined_spread / 2.0)


def is_wearing_head_covering(image: np.ndarray, points: np.ndarray) -> bool:
    """image — cv2.imdecode(...) natijasi (BGR), points — PoseLandmarks.points."""
    bbox = head_top_bbox(points, image.shape[1], image.shape[0])
    if bbox is None:
        return False
    return color_uniformity(image, bbox) >= settings.head_covering_uniformity_threshold
