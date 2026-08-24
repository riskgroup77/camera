"""TT kriteriya 10 ("Oq xalat kiyilganligi") — klassik rang tahliliga
asoslangan TAXMINIY aniqlash, chuqur o'qitilgan model EMAS.

Honest scope: seed.py'dagi asl reja "Kiyim klassifikatsiyasi (fine-tuned
YOLO/CLIP)" edi — bunday model haqiqiy, xilma-xil (turli burchak,
yorug'lik, masofa, xira tasvir) minglab BELGILANGAN CCTV kadrlari bilan
o'qitilishi kerak; bunday ma'lumot bazasi mavjud emas va bu loyihada
tashqi AI API (masalan GPT-4V) ishlatilmaydi. Foydalanuvchi yuborgan 6 ta
namuna — bular studiyada olingan, neytral fonli, yagona kiyim mahsulot
fotolari, real CCTV kadriga (turli burchak/yorug'lik/masofa/xiralik)
mutlaqo o'xshamaydi — ular bilan haqiqiy klassifikator o'qitib bo'lmaydi,
ular faqat "oq rang qanday ko'rinadi" degan diapazonni tasdiqlash uchun
ishlatildi.

Shu sababli bu yerda mediapipe pose'dan olingan tana (elka-son) hududi
bo'yicha klassik HSV rang tahlili qilinadi: agar shu hudud
pikselarining katta qismi "oq" diapazonda (yuqori yorqinlik V, past
to'yinganlik S) bo'lsa — oq xalat kiyilgan deb hisoblanadi.

Bilib turilgan cheklovlar (kamaytirilmagan, faqat ro'yxatga olingan):
- Yorug'lik sharoiti va kameraning oq balansi natijani o'zgartiradi.
- Oddiy oq ko'ylak/futbolka ham xuddi shunday signal beradi — bu haqiqatan
  "xalat" ekanligini emas, faqat "tan sohasi asosan oq" ekanligini
  tekshiradi.
- Haqiqiy institut kamerasi kadri bilan hali sinovdan o'tkazilmagan —
  faqat sintetik (qo'lda tuzilgan) test rasmlarida tekshirilgan
  (tests/test_coat_detection.py). Ishga tushirilgach, chindan ham qanday
  ishlashini kuzatib, kerak bo'lsa bo'sag'alarni qayta kalibrlash kerak
  bo'ladi — bu boshqa har bir yangi evristika bilan shu loyihada
  qilingani kabi.
"""

import cv2
import numpy as np

from app.config import settings
from app.services.pose_detection import LEFT_HIP, LEFT_SHOULDER, RIGHT_HIP, RIGHT_SHOULDER


def torso_bbox(points: np.ndarray, frame_width: int, frame_height: int) -> tuple[int, int, int, int] | None:
    """Elka-son hududining piksel-fazodagi (x1, y1, x2, y2) chegarasi,
    pastga (tizza tomon) kengaytirilgan — xalat sonlardan pastga
    tushadi. Elka/son landmarklari yetarlicha ko'rinmasa None."""
    required = [LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP]
    if not all(points[i][3] >= settings.coat_min_landmark_visibility for i in required):
        return None

    shoulder_y = (points[LEFT_SHOULDER][1] + points[RIGHT_SHOULDER][1]) / 2
    hip_y = (points[LEFT_HIP][1] + points[RIGHT_HIP][1]) / 2
    xs = [points[i][0] for i in required]
    torso_height = hip_y - shoulder_y
    if torso_height <= 0:
        return None

    x1 = max(0.0, min(xs) - 0.03)
    x2 = min(1.0, max(xs) + 0.03)
    y1 = max(0.0, shoulder_y - 0.02)
    y2 = min(1.0, hip_y + torso_height * settings.coat_torso_extension_factor)

    px1, py1 = int(x1 * frame_width), int(y1 * frame_height)
    px2, py2 = int(x2 * frame_width), int(y2 * frame_height)
    if px2 <= px1 or py2 <= py1:
        return None
    return px1, py1, px2, py2


def white_fraction(image: np.ndarray, bbox: tuple[int, int, int, int]) -> float:
    """bbox ichidagi piksellarning necha foizi "oq" HSV diapazonida
    ekanligi (0.0-1.0). image — BGR (cv2.imdecode natijasi)."""
    x1, y1, x2, y2 = bbox
    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        return 0.0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    saturation, value = hsv[:, :, 1], hsv[:, :, 2]
    white_mask = (saturation <= settings.coat_white_saturation_max) & (value >= settings.coat_white_value_min)
    return float(np.count_nonzero(white_mask)) / float(white_mask.size)


def is_wearing_white_coat(image: np.ndarray, points: np.ndarray) -> bool:
    """image — cv2.imdecode(...) natijasi (BGR), points — PoseLandmarks.points."""
    bbox = torso_bbox(points, image.shape[1], image.shape[0])
    if bbox is None:
        return False
    return white_fraction(image, bbox) >= settings.coat_white_fraction_threshold
