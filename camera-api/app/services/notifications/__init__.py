"""Bildirishnomalar — tizimning qolgan qismi uchun yagona kirish nuqtasi.

Hodisalar, kamera holati, davomat va boshqa joylar faqat shu yerdagi
funksiyalarni chaqiradi; qaysi kanal (Telegram, SMS), qaysi qoida va
qaysi qabul qiluvchi — bu paketning ichki ishi (dispatcher.py).

Qoidalar:
- Hech bir funksiya chaqiruvchini to'xtatmaydi: xato yutiladi va
  notification_log'ga yoziladi. Bildirishnoma yuborilmagani sababli
  hodisa yoki davomat yozilmay qolishi mumkin emas.
- Tarmoq so'rovlari fonda (asyncio task) ketadi — AI sweep kutib turmaydi.
"""

from app.services.notifications.dispatcher import (
    notify_absences,
    notify_access_denied,
    notify_attendance,
    notify_camera_status,
    notify_event,
    notify_event_overdue,
    notify_user,
)

__all__ = [
    "notify_event",
    "notify_event_overdue",
    "notify_camera_status",
    "notify_attendance",
    "notify_absences",
    "notify_access_denied",
    "notify_user",
]
