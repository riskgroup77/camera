"""Real vaqt rejimidagi (ANALYSIS_MODE=realtime) eski kriteriyalar — 3, 20, 26.
Buyurtmachi qarori bilan (2026-10-04) ular ishlab chiqarish ro'yxatidan olib
tashlangan (alembic z1a2b3c4d5e6), lekin real vaqt kodi hozircha saqlanadi va
uning testlari shu modullar bazada bo'lishini kutadi. 1 (begona shaxs)
2026-10-06 dan yana asosiy ro'yxatda (app/seed.py); 2 (taqiqlangan zona)
kodi bilan birga olib tashlangan. Faqat testlar uchun: tests/conftest.py
`seeded` fiksturasi."""

LEGACY_TRIAL_CODES: set[int] = set()

LEGACY_AI_MODULES = [
    {"code": 3, "group": "A", "name": "Notekis/kechki vaqtda kirish", "description": "Ish vaqtidan tashqari binoga kirish holatlari", "method": "Yuzni tanish orqali avtomatik davomat (app/jobs/attendance_ai.py) + ish vaqti oynasi qoidasi", "accuracy": 0, "threshold": 70, "sensitivity": "o'rta", "camera_count": 28, "active": True},
    {"code": 20, "group": "E", "name": "Talabaning uxlab qolishi", "description": "Ko'zning uzoq muddat yopiq qolishi (EAR) orqali uxlab qolishni aniqlash — bir necha kadrli (burst) ko'pchilik ovoz qoidasi + boshning kameraga qaragan-qaramaganini tekshiruvchi filtr bilan kuchaytirilgan (avvalgi 2-kadrli usuldan farqli); accuracy raqami hali yangi usul bilan qayta o'lchanmagan, eski qiymat sifatida qoldirilgan", "method": "Facial landmark + eye-closure (EAR) + burst-vote + pose-gate tahlili (app/jobs/vision_ai.py, app/services/sleep_detection.py)", "accuracy": 0, "threshold": 70, "sensitivity": "past", "camera_count": 28, "active": True},
    {"code": 26, "group": "E", "name": "O'qituvchi o'rniga boshqasi kirgani", "description": "Jadvalga ko'ra dars o'tishi kerak bo'lgan o'qituvchi o'rniga BOSHQA ro'yxatdan o'tgan xodim auditoriyada bo'lsa signal. #22 bilan bitta kadr, bitta detect_faces() chaqiruvidan foydalanadi — farq faqat solishtirish doirasida: #22 faqat rejadagi o'qituvchini qidiradi, bu esa barcha tasdiqlangan biometrikaga ega xodimlarni. Uch holat aniq ajratiladi: o'qituvchi joyida (hodisa yo'q), boshqa xodim joyida (#26), hech kim tanilmadi (#22 kelmagan). Talabalar solishtirishga kiritilmaydi — auditoriyada talaba bo'lishi tabiiy. Har bir signal dalil rasm bilan yoziladi, chunki \"kim kirgan\" degan savolga faqat rasm javob beradi", "method": "InsightFace + xodimlar bo'yicha to'liq moslik qidiruvi + LessonSession jadvali (app/jobs/teacher_punctuality_ai.py)", "accuracy": 0, "threshold": 70, "sensitivity": "o'rta", "camera_count": 0, "active": True},
]
