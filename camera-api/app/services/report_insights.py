"""Hisobotning "Qisqa xulosa" bloki — deterministik qoidalar, LLM emas.

Rahbar hisobotni ochganda birinchi 30 soniyada bitta savolga javob
qidiradi: "nimaga e'tibor berishim kerak?". Raqamlar jadvali bunga javob
bermaydi — shuning uchun har bir qoida aniq chegara bilan tekshiriladi va
natija oddiy tilda, raqami bilan, keyingi qadam havolasi bilan beriladi.

Qoidalar ataylab sodda va sinovdan o'tkaziladigan: har biri
tests/test_report_insights.py da chegaradan oldin va keyin tekshiriladi.
Kirish ma'lumoti InsightInputs — tahlilning to'liq tuzilmasi emas, shunda
qoidalarni bazasiz sinash mumkin.
"""

from dataclasses import dataclass, field

from app.config import settings
from app.schemas.report import InsightOut
from app.services.attendance_policy import current_policy

LEVEL_ORDER = {"critical": 0, "warning": 1, "info": 2, "ok": 3}
MAX_INSIGHTS = 6

ATTENDANCE_DROP_PP = 5.0
MIN_SAMPLE_FOR_TREND = 30
LATE_SHARE_WARN = 15.0
CAMERA_SHARE_WARN = 40.0
CAMERA_SHARE_MIN_EVENTS = 20
WEAK_PRECISION = 50.0
MAX_WEAK_MODULES = 2
LIVE_RATE_WARN = 90.0
LIVE_RATE_CRITICAL = 70.0
STUDENT_COVERAGE_INFO = 50.0
NIGHT_SHARE_INFO = 0.10
NIGHT_MIN_EVENTS = 5


@dataclass
class InsightInputs:
    staff_rate: float | None = None
    staff_previous_rate: float | None = None
    staff_previous_records: int = 0
    staff_reliable: bool = False
    staff_records: int = 0
    staff_present: int = 0
    staff_late_share: float | None = None
    stale_serious_unreviewed: int = 0
    oldest_unreviewed_hours: float | None = None
    total_events: int = 0
    night_events: int = 0
    top_camera_name: str | None = None
    top_camera_share: float | None = None
    # (modul nomi, aniqlik %, ko'rib chiqilgan signallar soni)
    weak_modules: list[tuple[str, float, int]] = field(default_factory=list)
    cameras_active: int = 0
    cameras_live_rate: float | None = None
    students_coverage: float | None = None
    students_population: int = 0


def _staff_late_after() -> str:
    """Xodim kechikish chegarasi — kech_keldi qaysi qoidadan yozilgan bo'lsa
    o'sha (ATTENDANCE_ARRIVAL_ONLY: attendance_policy, 08:00 + 10 daqiqa)."""
    if settings.attendance_arrival_only:
        return current_policy().late_after("xodim").strftime("%H:%M")
    return settings.attendance_ai_late_cutoff


def _num(value: float) -> str:
    """75.0 -> "75", 33.3 -> "33,3" — matnda o'qish oson bo'lsin."""
    text = f"{value:.1f}"
    if text.endswith(".0"):
        text = text[:-2]
    return text.replace(".", ",")


def build_insights(i: InsightInputs) -> list[InsightOut]:
    out: list[InsightOut] = []

    if i.staff_records > 0 and i.staff_present == 0:
        out.append(
            InsightOut(
                level="critical",
                title="Kameralar birorta xodimni tanimagan",
                text=(
                    f"Davrdagi {i.staff_records} ta davomat yozuvining birortasi \"keldi\" emas. Bu hamma kelmaganini "
                    "emas, yuzni tanish ishlamaganini bildiradi."
                ),
                action_label="Davomat kameralari tashxisi",
                action_href="/oqituvchilar",
            )
        )
    elif (
        i.staff_reliable
        and i.staff_rate is not None
        and i.staff_previous_rate is not None
        and i.staff_previous_records >= MIN_SAMPLE_FOR_TREND
        and i.staff_previous_rate - i.staff_rate >= ATTENDANCE_DROP_PP
    ):
        drop = i.staff_previous_rate - i.staff_rate
        out.append(
            InsightOut(
                level="warning",
                title="Xodimlar davomati pasaydi",
                text=(
                    f"Oldingi davrdagi {_num(i.staff_previous_rate)}% dan {_num(i.staff_rate)}% ga tushdi "
                    f"({_num(drop)} foiz punkt kam)."
                ),
                action_label="Davomat kalendari",
                action_href="/talabalar",
            )
        )

    if i.staff_reliable and i.staff_late_share is not None and i.staff_late_share >= LATE_SHARE_WARN:
        out.append(
            InsightOut(
                level="warning",
                title="Kech qolish ko'p",
                text=(
                    f"Kelgan xodimlarning {_num(i.staff_late_share)}% i soat "
                    f"{_staff_late_after()} dan keyin kelgan."
                ),
                action_label="Davomat kalendari",
                action_href="/talabalar",
            )
        )

    if i.stale_serious_unreviewed > 0:
        age = (
            f" Eng eski ko'rilmagan signal {_num(i.oldest_unreviewed_hours)} soat oldin kelgan."
            if i.oldest_unreviewed_hours is not None
            else ""
        )
        out.append(
            InsightOut(
                level="critical",
                title="Jiddiy signallar ko'rib chiqilmagan",
                text=(
                    f"{i.stale_serious_unreviewed} ta o'rta yoki yuqori muhimlikdagi signal 24 soatdan ortiq "
                    f"navbatda turibdi.{age}"
                ),
                action_label="Hodisalar jurnali",
                action_href="/hodisalar",
            )
        )

    if (
        i.top_camera_name
        and i.top_camera_share is not None
        and i.total_events >= CAMERA_SHARE_MIN_EVENTS
        and i.top_camera_share >= CAMERA_SHARE_WARN
    ):
        out.append(
            InsightOut(
                level="warning",
                title="Signallarning ko'pi bitta kameradan",
                text=(
                    f"«{i.top_camera_name}» barcha signallarning {_num(i.top_camera_share)}% ini bergan. Odatda bu "
                    "hodisalar ko'pligini emas, kameraning ko'rish maydonidagi muammoni bildiradi."
                ),
                action_label="Kameralar",
                action_href="/sozlamalar/kameralar",
            )
        )

    for name, precision, reviewed in sorted(i.weak_modules, key=lambda m: m[1])[:MAX_WEAK_MODULES]:
        out.append(
            InsightOut(
                level="warning",
                title="Modul ko'p yolg'on signal bermoqda",
                text=(
                    f"«{name}»: operatorlar ko'rib chiqqan {reviewed} ta signalning faqat {_num(precision)}% i "
                    "tasdiqlangan. Chegarasini oshirish yoki kamerani tekshirish kerak."
                ),
                action_label="AI modullar",
                action_href="/sozlamalar/ai",
            )
        )

    if i.cameras_active > 0 and i.cameras_live_rate is not None and i.cameras_live_rate < LIVE_RATE_WARN:
        out.append(
            InsightOut(
                level="critical" if i.cameras_live_rate < LIVE_RATE_CRITICAL else "warning",
                title="Kameralarning bir qismi ishlamayapti",
                text=(
                    f"Faol kameralarning {_num(100 - i.cameras_live_rate)}% i hozir aloqada emas — ular ko'rgan "
                    "joylar kuzatilmayapti."
                ),
                action_label="Kameralar",
                action_href="/sozlamalar/kameralar",
            )
        )

    if (
        i.students_population > 0
        and i.students_coverage is not None
        and i.students_coverage < STUDENT_COVERAGE_INFO
    ):
        out.append(
            InsightOut(
                level="info",
                title="Talabalar davomati to'liq emas",
                text=(
                    f"Talabalarning atigi {_num(i.students_coverage)}% i yuzini tasdiqlagan. Qolganlarini kameralar "
                    "tanimaydi, shuning uchun talabalar davomati foizi butun institutni aks ettirmaydi."
                ),
                action_label="Talabalar va Xodimlar",
                action_href="/reestr",
            )
        )

    if i.total_events >= NIGHT_MIN_EVENTS and i.night_events / i.total_events >= NIGHT_SHARE_INFO:
        out.append(
            InsightOut(
                level="info",
                title="Ish vaqtidan tashqari signallar",
                text=(
                    f"{i.night_events} ta signal soat 07:00–21:00 dan tashqarida, bino bo'sh paytda qayd etilgan — "
                    "ularni alohida ko'rib chiqish kerak."
                ),
                action_label="Hodisalar jurnali",
                action_href="/hodisalar",
            )
        )

    if not out:
        out.append(
            InsightOut(
                level="ok",
                title="Jiddiy og'ish aniqlanmadi",
                text="Tanlangan davrda alohida e'tibor talab qiladigan holat topilmadi.",
            )
        )

    out.sort(key=lambda insight: LEVEL_ORDER[insight.level])
    return out[:MAX_INSIGHTS]
