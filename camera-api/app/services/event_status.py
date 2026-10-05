"""Hodisa ish jarayoni holatlari — bitta joyda.

yangi -> jarayonda -> tasdiqlangan / rad_etilgan -> hal_qilindi.

Statistika uchun ma'no (routerlar, hisobotlar va analitika shu yerdan oladi):
- "yangi" va "jarayonda" — hali qaror qilinmagan (ko'rib chiqilmagan);
- "tasdiqlangan" va "hal_qilindi" — signal haqiqiy (hal qilingan hodisa
  avval haqiqiy deb topilgan), aniqlik foizida "tasdiqlangan" hisoblanadi;
- "rad_etilgan" — yolg'on signal.
"""

from collections.abc import Mapping

STATUSES = ("yangi", "jarayonda", "tasdiqlangan", "rad_etilgan", "hal_qilindi")

# Qaror kutayotgan hodisalar — SLA muddati va eskalatsiya shularga tegishli.
OPEN_STATUSES = ("yangi", "jarayonda")
# Aniqlik foizida "haqiqiy signal" deb hisoblanadiganlar.
CONFIRMED_STATUSES = ("tasdiqlangan", "hal_qilindi")
REJECTED_STATUSES = ("rad_etilgan",)
# Kimdir ustida ishlashi kerak bo'lganlar: "Menga tayinlangan" hisobi.
ACTIVE_STATUSES = ("yangi", "jarayonda", "tasdiqlangan")

STATUS_LABELS = {
    "yangi": "Ko'rilmagan",
    "jarayonda": "Jarayonda",
    "tasdiqlangan": "Tasdiqlangan",
    "rad_etilgan": "Rad etilgan",
    "hal_qilindi": "Hal qilindi",
}

# Ruxsat etilgan o'tishlar. Yolg'on signal (rad_etilgan) "hal qilinmaydi":
# u haqiqiy hodisa emas, hal_qilindi esa statistikada tasdiqlangan
# hisoblanadi. "yangi" ga faqat jarayondagi hodisa qaytariladi (navbatga).
TRANSITIONS: dict[str, frozenset[str]] = {
    "yangi": frozenset({"jarayonda", "tasdiqlangan", "rad_etilgan", "hal_qilindi"}),
    "jarayonda": frozenset({"yangi", "tasdiqlangan", "rad_etilgan", "hal_qilindi"}),
    "tasdiqlangan": frozenset({"jarayonda", "rad_etilgan", "hal_qilindi"}),
    "rad_etilgan": frozenset({"jarayonda", "tasdiqlangan"}),
    "hal_qilindi": frozenset({"jarayonda", "tasdiqlangan", "rad_etilgan"}),
}


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, frozenset())


def fold_review_counts(status_counts: Mapping[str, int]) -> dict[str, int]:
    """Holat bo'yicha sonlarni eski uch toifaga yig'adi: yangi (qaror
    qilinmagan), tasdiqlangan (haqiqiy), rad_etilgan. Uch toifali eski
    hisobot va analitika shakllari shu orqali yangi holatlarni to'g'ri sanaydi."""
    return {
        "yangi": sum(int(status_counts.get(s, 0)) for s in OPEN_STATUSES),
        "tasdiqlangan": sum(int(status_counts.get(s, 0)) for s in CONFIRMED_STATUSES),
        "rad_etilgan": sum(int(status_counts.get(s, 0)) for s in REJECTED_STATUSES),
    }


# Uch toifali hisobot "bucket" kaliti -> bazadagi holatlar (drill-down eksporti uchun).
REVIEW_BUCKET_STATUSES: dict[str, tuple[str, ...]] = {
    "yangi": OPEN_STATUSES,
    "tasdiqlangan": CONFIRMED_STATUSES,
    "rad_etilgan": REJECTED_STATUSES,
}


def bucket_statuses(bucket: str) -> tuple[str, ...]:
    return REVIEW_BUCKET_STATUSES.get(bucket, (bucket,))


def review_bucket(status: str) -> str:
    """Bitta holatning uch toifali (yangi / tasdiqlangan / rad_etilgan) kaliti."""
    if status in OPEN_STATUSES:
        return "yangi"
    if status in CONFIRMED_STATUSES:
        return "tasdiqlangan"
    return status
