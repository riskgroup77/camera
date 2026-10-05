"""Xodim matnidan (group_or_position) bo'linmani ishonchli ajratish.

Production'dagi haqiqiy holat (2026-09-19): 785 xodimda 158 xil yozuv, ularning
yarmi bo'linma emas, LAVOZIM — va har xil imloda: "Assistent", "Asisent",
"Assitent", "ASSISTENT", "Ассистент", "Stajyor-o'qituvchi", "stajor o'qituvchi",
"Коровул"... Bundan tashqari bitta bo'linma ikki xil yozilgan
("Patologik fiziologiya va patologik anatomiya" / "Potologik fizologiya
potologik anatomiya").

Bu modul bazadagi ma'lumotni O'ZGARTIRMAYDI — faqat o'qishda talqin qiladi:
  * unit_key()     — solishtirish kaliti: kirill -> lotin, apostrof va tire
                     olib tashlanadi, kichik harf, bo'shliqlar bitta;
  * is_position()  — matn faqat lavozim(lar)dan iboratmi (imlo xatolari bilan);
  * cluster_keys() — deyarli bir xil kalitlarni bitta bo'linmaga birlashtiradi
                     (raqamlari farq qiladiganlari hech qachon qo'shilmaydi:
                     "Pediatriya" va "Pediatriya-2", "1-" va "3-turar joy").
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from difflib import SequenceMatcher

_CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z", "и": "i",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ы": "i", "ь": "",
    "э": "e", "ю": "yu", "я": "ya", "ў": "o", "қ": "q", "ғ": "g", "ҳ": "h",
}
_STRIP = "'`‘’ʻʼ´\""


def unit_key(text: str | None) -> str:
    value = (text or "").lower()
    value = "".join(_CYRILLIC.get(ch, ch) for ch in value)
    for ch in _STRIP:
        value = value.replace(ch, "")
    value = re.sub(r"[-–—_.,;:()/\\]+", " ", value)
    return " ".join(value.split())


# Lavozim so'zlarining "o'zagi" — imlo xatolariga chidamli bo'lishi uchun
# muntazam ifoda. Yangi lavozim chiqsa SHU ro'yxatga qo'shing.
_POSITION_PATTERNS = [
    r"a+s+i+s+t?[ae]?n?t?[a-z]*",  # assistent, asisent, asissent, assitent, assistant, assisten
    r"as+i+[st]+e?n?t?[a-z]*",  # asistent, asisstent, assisent
    r"o?q[iu]?t[iu]?v?chi[a-z]*", r"ukituvchi", r"oqtuvchi",  # o'qituvchi (kirill: укитувчи)
    r"staj[yi]?[oe]?r", r"stajior", r"stable",  # stajyor, stajor, stajer
    r"tyutor", r"uslubchi", r"menejer", r"auditor", r"dotsent", r"professor", r"phd",
    r"lab[ao]rant", r"farr?[ao]sh", r"[qk]orov[u]?l", r"supuruvchi", r"dur[ao]dgor",
    r"elektr[a-z]*", r"registrator", r"mudir[a-z]*", r"mutaxassis[a-z]*", r"boshlig[a-z]*",
    r"maslahatchi[a-z]*", r"bekasi", r"yurituvchi", r"[hx]isobchi", r"muhandis[a-z]*", r"muxandis[a-z]*",
    r"akusher", r"gin[ie]kolog", r"vrach", r"hamshira", r"kutubxonachi", r"haydovchi", r"oshpaz",
    r"qorovul", r"kotib[a-z]*", r"operator", r"dasturchi", r"metodist", r"inspektor", r"tarjimon",
    r"rektor", r"prorektor", r"dekan", r"orinbosari?", r"rahbar[a-z]*", r"direktor", r"ishchi", r"texnik",
    r"xodim", r"yordamchi", r"psixolog", r"yurist", r"tadqiqotchi", r"santexnik", r"bogbon", r"omborchi",
]
_POSITION_RE = re.compile(r"^(?:" + "|".join(_POSITION_PATTERNS) + r")$")
# Lavozim yonida keladigan, o'zi bo'linma bildirmaydigan so'zlar.
_MODIFIERS = frozenset({
    "bosh", "katta", "kichik", "yetakchi", "oliy", "toifali", "va", "ilmiy", "tashqi", "tashi", "orindosh",
    "son", "ttj", "kafedra", "kafedrasi", "bolim", "kabinet", "kabi", "net", "ish", "m", "x", "mmx",
    "doesnt", "vaqtincha", "orinbosar", "elektron", "xojalik", "1", "2", "3", "4",
})


def is_position(text: str | None) -> bool:
    """Matn bo'linma emas, faqat lavozim (masalan "Katta o'qituvchi",
    "Tashi orindosh.Asistent", "кафедра ассистенти"). Bo'sh matn ham shunday."""
    tokens = unit_key(text).split()
    if not tokens:
        return True
    has_position = False
    for token in tokens:
        if _POSITION_RE.match(token):
            has_position = True
        elif token not in _MODIFIERS:
            return False
    return has_position


def _digits(key: str) -> tuple[str, ...]:
    return tuple(re.findall(r"\d+", key))


def _similar(a: str, b: str) -> bool:
    if _digits(a) != _digits(b):
        return False
    ta, tb = a.split(), b.split()
    # Birinchi so'z kamida bir-biriga o'xshash bo'lishi kerak — butunlay boshqa
    # bo'linmalar umumiy "va ... gigienasi" qismi tufayli qo'shilib ketmasin.
    if SequenceMatcher(None, ta[0], tb[0]).ratio() < 0.75:
        return False
    return SequenceMatcher(None, a, b).ratio() >= 0.8


def cluster_keys(counts: Mapping[str, int]) -> dict[str, str]:
    """kalit -> kanonik kalit. Kanonik — guruhdagi eng ko'p odamli yozilish.

    Kattaroq bo'linmalar birinchi ko'riladi: kichik (imlo xatoli) variant
    o'ziga o'xshash katta bo'linmaga qo'shiladi, aksincha emas."""
    canon: dict[str, str] = {}
    heads: list[str] = []
    for key in sorted(counts, key=lambda k: (-counts[k], k)):
        target = next((head for head in heads if _similar(key, head)), None)
        if target is None:
            heads.append(key)
            canon[key] = key
        else:
            canon[key] = target
    return canon


def canonical_map(names: Iterable[str | None]) -> dict[str, str]:
    """Matnlar ro'yxatidan: unit_key -> kanonik unit_key (lavozimlar kirmaydi)."""
    counts: dict[str, int] = {}
    for name in names:
        if is_position(name):
            continue
        key = unit_key(name)
        counts[key] = counts.get(key, 0) + 1
    return cluster_keys(counts)
