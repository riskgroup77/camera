"""Hodisa bo'yicha operator ko'rsatmasi (SOP — standart harakat tartibi).

Milestone'dagi "alarm instructions" kabi: operator hodisani ochganda
nima qilish kerakligini qisqa qadamlar ro'yxati sifatida ko'radi. Yangi
operator ham, tungi navbatdagi charchagan operator ham bir xil tartibda
harakat qilishi uchun.

Matn modulga bog'langan (ai_modules.sop, har qatorda bitta qadam).
Ustun bo'sh bo'lsa shu yerdagi standart ishlatiladi — standartni kodda
yaxshilash barcha "o'zgartirilmagan" modullarga darhol tarqaladi.
"""

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AIModuleConfig

#: Qadamlar soni va uzunligi chegarasi — ko'rsatma panel ichida qisqa
#: ro'yxat bo'lib qolishi kerak, qo'llanma emas.
MAX_STEPS = 10
MAX_STEP_LENGTH = 200

DEFAULT_SOP: dict[int, str] = {
    1: (
        "Kadrdagi yuzni ko'rib, haqiqatan notanish ekanini tekshiring\n"
        "Jonli kamerada odam hozir qayerdaligini aniqlang\n"
        "Eng yaqin qo'riqchini joyga yuboring\n"
        "Shaxsi aniqlansa — natijani izohga yozing va hodisani yoping"
    ),
    2: (
        "Jonli kamerada zonada kim borligini tekshiring\n"
        "Ruxsati bor xodim bo'lsa — rad eting\n"
        "Ruxsatsiz bo'lsa — qo'riqchini zonaga yuboring\n"
        "Zona mas'uliga xabar bering va natijani izohga yozing"
    ),
    3: (
        "Kadrdagi odam va kirish vaqtini tekshiring\n"
        "Ish vaqtidan tashqari ruxsati bormi — mas'uldan so'rang\n"
        "Ruxsat yo'q bo'lsa — qo'riqchini yuboring\n"
        "Natijani izohga yozib, hodisani yoping"
    ),
    6: (
        "Xodimning kirish-chiqish vaqtini tekshiring\n"
        "Xato tanilgan bo'lsa — rad eting\n"
        "Kerak bo'lsa bo'lim rahbariga xabar bering"
    ),
    7: (
        "Talaba va dars ma'lumotlarini tekshiring\n"
        "Xato tanilgan bo'lsa — rad eting\n"
        "Kerak bo'lsa guruh kuratoriga xabar bering"
    ),
    8: (
        "Dars jadvali va kelish vaqtini solishtiring\n"
        "Uzrli sabab bo'lsa — izohga yozing\n"
        "Takrorlansa kuratorga xabar bering"
    ),
    9: (
        "Dars tugash vaqti va oxirgi ko'rinishni solishtiring\n"
        "Uzrli sabab bo'lsa — izohga yozing\n"
        "Takrorlansa kuratorga xabar bering"
    ),
    19: (
        "Sinf kamerasida dars holatini ko'ring\n"
        "Past diqqat davom etsa — o'quv bo'limiga xabar bering\n"
        "Natijani izohga yozing"
    ),
    20: (
        "Kadrda talaba haqiqatan uxlayotganini tekshiring\n"
        "Pastga qarab yozayotgan bo'lsa — rad eting\n"
        "Tasdiqlansa — dars o'qituvchisiga xabar bering\n"
        "Natijani izohga yozing"
    ),
    21: (
        "Sinf kamerasida dars holatini ko'ring\n"
        "Past faollik davom etsa — o'quv bo'limiga xabar bering\n"
        "Natijani izohga yozing"
    ),
    22: (
        "Jonli kamerada auditoriyani tekshiring\n"
        "O'qituvchiga yoki kafedraga qo'ng'iroq qiling\n"
        "Dars bekor bo'lsa — o'quv bo'limiga xabar bering\n"
        "Sababni izohga yozing"
    ),
    26: (
        "Kadrdagi xodim kimligini tekshiring\n"
        "Kafedradan almashtirish rasmiylashtirilganini so'rang\n"
        "Rasmiy bo'lsa — rad eting, izohga yozing\n"
        "Rasmiy bo'lmasa — o'quv bo'limiga xabar bering"
    ),
}

#: Modulga xos standart bo'lmasa (yangi modul) — umumiy tartib.
GENERIC_SOP = (
    "Kadr va jonli kamerani tekshiring\n"
    "Yolg'on signal bo'lsa — rad eting\n"
    "Kerak bo'lsa mas'ulga xabar bering\n"
    "Natijani izohga yozing"
)


def parse_steps(text: str | None) -> list[str]:
    """Matn → qadamlar. Bo'sh qatorlar va boshidagi "1." / "-" belgilar
    tashlanadi: administrator ro'yxatni qanday yozsa ham bir xil chiqsin."""
    steps: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("-•*").strip()
        head, dot, rest = line.partition(".")
        if dot and head.isdigit():
            line = rest.strip()
        if line:
            steps.append(line[:MAX_STEP_LENGTH])
    return steps[:MAX_STEPS]


def default_steps(module_code: int) -> list[str]:
    return parse_steps(DEFAULT_SOP.get(module_code, GENERIC_SOP))


def resolve_steps(module_code: int, custom: str | None) -> list[str]:
    """Modul uchun amaldagi qadamlar: o'zgartirilgan matn yoki standart."""
    steps = parse_steps(custom)
    return steps or default_steps(module_code)


async def load_sops(db: AsyncSession, codes: Iterable[int]) -> dict[int, list[str]]:
    """Bir nechta modul uchun qadamlar bitta so'rovda (hodisalar ro'yxati)."""
    wanted = set(codes)
    if not wanted:
        return {}
    rows = (
        await db.execute(select(AIModuleConfig.code, AIModuleConfig.sop).where(AIModuleConfig.code.in_(wanted)))
    ).all()
    custom = {code: sop for code, sop in rows}
    return {code: resolve_steps(code, custom.get(code)) for code in wanted}
