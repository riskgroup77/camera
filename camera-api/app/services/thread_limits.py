"""Hisoblash kutubxonalarining ichki oqimlar sonini cheklash.

MUAMMO. PyTorch (YOLO obyekt va poza) va OpenCV standart bo'yicha HOSTdagi
barcha yadrolarni ko'radi. Docker'ning `cpus: 20` chegarasi — CFS kvotasi,
cpuset emas: konteyner ichida os.cpu_count() baribir 32 ni beradi.
Productionda parallel ishlaydigan 8 ta YOLO va 6 ta poza chaqiruvining har
biri o'z 32 oqimli havzasini ochardi — 20 yadroli kvotada yuzlab oqim.
Kvota tugagach yadro butun konteynerni to'xtatib turadi (throttling), va
bundan AI emas, API javoblari ham sekinlashadi.

YECHIM. Har chaqiruv kam oqimda ishlaydi, parallellikni esa
inference_gate / obyekt semaforlari beradi: umumiy oqimlar ≈ parallel
chaqiruvlar × shu son. InsightFace sessiyalari o'z chegarasini
face_recognition._limit_session_threads orqali oladi.

OMP_NUM_THREADS / OPENBLAS_NUM_THREADS / MKL_NUM_THREADS bu yerda emas,
env'da beriladi (deploy/env.production.scale): ular kutubxona yuklanganda
bir marta o'qiladi, ishga tushgandan keyin o'zgartirib bo'lmaydi.
"""

from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger("app.thread_limits")


def apply_thread_limits() -> dict[str, int | None]:
    """Sozlamadagi chegaralarni qo'llaydi va amaldagi qiymatlarni qaytaradi.

    Har jarayonda bir marta, ishga tushishda chaqiriladi (app/main.py).
    Kutubxona o'rnatilmagan bo'lsa (masalan torch'siz test muhiti) — jim
    o'tib ketadi: chegara kerak bo'lgan kod ham o'sha kutubxonasiz ishlamaydi."""
    applied: dict[str, int | None] = {"torch": None, "opencv": None}

    if settings.ai_torch_threads > 0:
        try:
            import torch
        except ImportError:
            torch = None  # type: ignore[assignment]
        if torch is not None:
            torch.set_num_threads(settings.ai_torch_threads)
            applied["torch"] = torch.get_num_threads()

    if settings.cv_internal_threads >= 0:
        import cv2

        cv2.setNumThreads(settings.cv_internal_threads)
        applied["opencv"] = cv2.getNumThreads()

    if any(value is not None for value in applied.values()):
        logger.info("compute library thread limits applied", extra=applied)
    return applied
