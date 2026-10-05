"""Application-level encryption for secrets that must be readable again
later (unlike passwords, which are one-way hashed) — e.g. camera RTSP
credentials, which the connectivity checker needs to decrypt to actually
dial the camera. Uses Fernet (AES-128-CBC + HMAC), keyed by ENCRYPTION_KEY.
"""

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

_fernet = Fernet(settings.encryption_key.encode())


def encrypt(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    try:
        return _fernet.decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Shifrlangan qiymatni ochib bo'lmadi — ENCRYPTION_KEY mos kelmayapti") from exc
