import re
from urllib.parse import quote

#: `scheme://user:pass@host` — parol qismini topish uchun. rtsp dan tashqari
#: rtsps/http(s) ham qamrab olinadi: ffmpeg/ffprobe xato satrida qaysi
#: sxemani qaytarishi kirish manziliga bog'liq.
_CREDENTIALS_IN_URL = re.compile(r"\b(rtsps?|https?)://[^\s/@]+@")


def build_rtsp_url(ip: str, port: int, path: str | None, username: str | None, password: str | None) -> str:
    if username and password:
        auth = f"{quote(username, safe='')}:{quote(password, safe='')}@"
    elif username:
        auth = f"{quote(username, safe='')}@"
    else:
        auth = ""
    suffix = path if path and path.startswith("/") else f"/{path}" if path else "/"
    return f"rtsp://{auth}{ip}:{port}{suffix}"


def redact_credentials(text: str) -> str:
    """URL ichidagi `user:pass@` ni `***:***@` bilan almashtiradi.

    ffmpeg va ffprobe xato satrlarida kirish URL'ini aynan qaytaradi
    (masalan 401/DESCRIBE xatosida), shuning uchun o'sha matn logga
    yozilishidan yoki HTTP javobiga tushishidan OLDIN shu yerdan
    o'tkaziladi — aks holda kameraning haqiqiy paroli ochiq ko'rinadi.
    """
    return _CREDENTIALS_IN_URL.sub(lambda m: f"{m.group(1)}://***:***@", text)
