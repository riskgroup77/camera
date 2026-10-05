"""Operator ko'radigan signallar doirasi — hodisalar jurnali, devor va statistika uchun umumiy.

Alohida modulda, chunki bir xil qoida bir necha routerda kerak: biri
unutilsa, devor sarlavhasidagi son pastdagi ro'yxatga mos kelmay qoladi.
"""

from sqlalchemy import and_, false, select

from app.models import AIModuleConfig, Event, ModuleCameraSuppression

# Faqat hozirgi reestrdagi modullar: olib tashlangan kriteriyalarning
# (#5, #12, #16, #25 ...) eski signallari navbatni, filtrlarni va devorni
# to'ldirmasligi kerak — ularni endi hech kim sozlay ham, tuzata ham olmaydi.
REGISTERED_MODULE = Event.module_code.in_(select(AIModuleConfig.code))

# Sinov signallari (is_trial) navbat va statistikaga aralashmaydi.
OPERATOR_EVENTS = and_(Event.is_trial == false(), REGISTERED_MODULE)

# Avtomatik o'chirilgan kamera×modul juftligi (ModuleCameraSuppression):
# uning eski signallari "hozirgi xavf" emas — devorda ko'rsatilmaydi.
NOT_SUPPRESSED = ~(
    select(ModuleCameraSuppression.id)
    .where(ModuleCameraSuppression.camera_id == Event.camera_id)
    .where(ModuleCameraSuppression.module_code == Event.module_code)
    .where(ModuleCameraSuppression.restored_at.is_(None))
    .exists()
)
