"""Password-reset email delivery. If SMTP is configured, a real email is
sent; otherwise (dev/no-SMTP environments) the reset link is written to the
structured log instead — the reset flow itself stays fully functional
either way, only the delivery channel changes."""

import logging
import smtplib
from email.message import EmailMessage

from app.config import settings

logger = logging.getLogger("app.email")


def send_password_reset_email(to_email: str, to_name: str, reset_link: str) -> None:
    if not settings.smtp_host:
        logger.warning(
            "SMTP sozlanmagan — parolni tiklash havolasi yuborilmadi, faqat logga yozildi",
            extra={"to": to_email, "reset_link": reset_link},
        )
        return

    message = EmailMessage()
    message["Subject"] = "Parolni tiklash — Situatsion Markaz"
    message["From"] = settings.smtp_from
    message["To"] = to_email
    message.set_content(
        f"Assalomu alaykum, {to_name}!\n\n"
        "Hisobingiz uchun parolni tiklash so'rovi yuborildi. Quyidagi havola "
        "orqali yangi parol o'rnatishingiz mumkin (30 daqiqa amal qiladi):\n\n"
        f"{reset_link}\n\n"
        "Agar bu so'rovni siz yubormagan bo'lsangiz, xabarni e'tiborsiz qoldiring — "
        "parolingiz o'zgarmaydi."
    )

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        # Email yetkazib bo'lmasa ham so'rov o'zi muvaffaqiyatli qayd etilgan
        # bo'lishi kerak (token allaqachon yaratilgan) — shuning uchun bu yerda
        # faqat log yozamiz, xatoni yuqoriga otmaymiz.
        logger.error(
            "parolni tiklash emailini yuborib bo'lmadi",
            extra={"to": to_email, "error": str(exc), "reset_link": reset_link},
        )
