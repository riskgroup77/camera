"""Odam ismini solishtirish — bir odam turli yozilganda ham tanish.

Ikki joyda ishlatiladi va ikkalasi AYNAN bir qoidaga tayanishi shart:

  * scripts/merge_duplicate_people.py — mavjud dublikatlarni birlashtiradi;
  * app/routers/students_staff.py — admin "Yangi biriktirish"da ro'yxatda
    allaqachon bor odamni qayta qo'shishining oldini oladi.

Real ma'lumotda uchragan farqlar: Salohiddin/Saloxiddin, Saydullaeva/
Saydullayeva, Qaxorovich/Koxorovich, teskari tartib ("Arslonbek Ikromiy"),
kirill yozuvi ("Махаматова Умидахон"), otasining ismi yozilmagan
("Kurbonova Aziza"), va "G‘offorjon-qizi" kabi chiziqcha bilan yozuv.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

_APOSTROPHES = "‘’`ʻʼ´"

_CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh",
    "ъ": "", "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya", "ў": "o", "қ": "q", "ғ": "g", "ҳ": "h",
}
# Otasining ismidan keyingi qo'shimchalar (fuzzy_word'dan keyingi shaklda)
_PARTICLES = {"ogli", "ugli", "ogil", "kizi", "kiz"}


def name_key(full_name: str | None) -> str:
    """Aniq moslik kaliti: faqat harf kattaligi, bo'shliq va tutuq belgisi
    shakli farqi e'tiborsiz."""
    text = full_name or ""
    for ch in _APOSTROPHES:
        text = text.replace(ch, "'")
    return " ".join(text.lower().split())


def fuzzy_word(word: str) -> str:
    """Bir so'zni yozilish farqlaridan tozalaydi: kirill -> lotin, tutuq va
    chiziqchalar, x/h, q/k, ye/yo/yu/ya, qo'sh harflar."""
    text = "".join(_CYRILLIC.get(ch, ch) for ch in word.lower())
    text = re.sub(r"[‘’`ʻʼ´'\-.]", "", text)
    for old, new in (("ye", "e"), ("yo", "o"), ("yu", "u"), ("ya", "a"), ("x", "h"), ("q", "k")):
        text = text.replace(old, new)
    return re.sub(r"(.)\1+", r"\1", text)


def name_tokens(full_name: str | None) -> list[str]:
    tokens = [fuzzy_word(t) for t in re.split(r"[\s\-]+", full_name or "") if t.strip(" '‘’`ʻʼ")]
    return [t for t in tokens if t and t not in _PARTICLES]


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _patronymic_close(a: str, b: str) -> bool:
    """Yaqin: umumiy o'xshashlik >= 0.80 ("Qaxorovich"/"Koxorovich" 0.90).
    Chegara ataylab qattiq: "Olimovich"/"Botirovich" — ikki xil ota — 0.74.

    Qo'shimcha yo'l faqat QISQA, kesilib qolgan yozuv uchun: "Toshqo 'ziyevich"
    bo'shliq sabab "Toshko" bo'lib qoladi. Uzun so'zlarga umumiy boshlanish
    yetarli emas — "Muhammadovich"/"Muhammadaliyevich" boshqa-boshqa ota."""
    if _ratio(a, b) >= 0.80:
        return True
    shorter, longer = sorted((a, b), key=len)
    common = 0
    for x, y in zip(shorter, longer):
        if x != y:
            break
        common += 1
    return len(shorter) <= 7 and common >= 5


def names_match(a: list[str], b: list[str]) -> bool:
    """Ikki odam nomi bir odamnikimi (name_tokens natijalari).

    * ism AYNAN mos, so'z tartibi ahamiyatsiz;
    * ikkalasida otasining ismi bo'lsa — familiya juda yaqin (>= 0.85) va
      otasining ismi ham yaqin bo'lishi shart;
    * birida otasining ismi yo'q bo'lsa — familiya AYNAN mos bo'lishi shart.
      Tekshiradigan uchinchi so'z yo'q, shuning uchun familiyadagi har qanday
      farq boshqa odamni anglatishi mumkin: "Ismoiljanova Nilufar" va
      "Ismoilova Nilufar" (0.86) — boshqa-boshqa odamlar."""
    if len(a) < 2 or len(b) < 2:
        return False
    both_patronymic = len(a) >= 3 and len(b) >= 3
    for surname, given in ((a[0], a[1]), (a[1], a[0])):
        if given != b[1]:
            continue
        if surname != b[0] and (not both_patronymic or _ratio(surname, b[0]) < 0.85):
            continue
        if both_patronymic and not _patronymic_close(a[2], b[2]):
            continue
        return True
    return False


def same_person_name(a: str | None, b: str | None) -> bool:
    return name_key(a) == name_key(b) or names_match(name_tokens(a), name_tokens(b))
