"""Kamera mas'uli foydalanuvchilarini yaratadi.

Serverda:
    cd /opt/camera/camera-api
    docker compose -f docker-compose.yml -f docker-compose.override.yml \
        exec -T api python scripts/create_camera_stewards.py

Ixtiyoriy argumentlar: soni (standart 5) va login prefiksi (standart
"kamera"). Masalan uchta qo'shimcha hisob:
    python scripts/create_camera_stewards.py 3 kamera-b

Parollar shu yerda, tasodifiy tarzda yaratiladi va FAQAT SHU CHIQISHDA
ko'rinadi — bazada faqat xesh saqlanadi, ya'ni keyin ularni qayta ko'rib
bo'lmaydi. Yo'qolsa, admin panelidagi "Parolni tiklash" orqali yangisi
qo'yiladi.

Mavjud login qayta yaratilmaydi: skriptni ikki marta ishga tushirish
xavfsiz, u faqat yetishmayotganlarini qo'shadi.
"""

import asyncio
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402
from app.security import hash_password  # noqa: E402

ROLE = "kamera-masuli"
# Chalkashtiradigan belgilar (0/O, 1/l/I) yo'q — parol og'zaki ham
# aytiladi va qo'lda ham kiritiladi.
ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"


def make_password() -> str:
    parts = ["".join(secrets.choice(ALPHABET) for _ in range(4)) for _ in range(3)]
    return "-".join(parts)


async def main(count: int, prefix: str) -> None:
    created: list[tuple[str, str, str]] = []
    skipped: list[str] = []

    async with SessionLocal() as db:
        for index in range(1, count + 1):
            login = f"{prefix}{index}"
            existing = (await db.execute(select(User).where(User.login == login))).scalar_one_or_none()
            if existing is not None:
                skipped.append(login)
                continue
            password = make_password()
            full_name = f"Kamera mas'uli {index}"
            db.add(
                User(
                    login=login,
                    password_hash=hash_password(password),
                    full_name=full_name,
                    role=ROLE,
                )
            )
            created.append((login, password, full_name))
        await db.commit()

    print()
    print("=" * 64)
    print("KAMERA MAS'ULI HISOBLARI")
    print("=" * 64)
    if created:
        print("login | parol | ism")
        for login, password, full_name in created:
            print(f"{login} | {password} | {full_name}")
    else:
        print("Yangi hisob yaratilmadi.")
    if skipped:
        print(f"\nAllaqachon mavjud (o'zgartirilmadi): {', '.join(skipped)}")
    print()
    print("Bu hisoblar faqat ikkita bo'limni ko'radi: Tashkiliy tuzilma va")
    print("Kameralar va Zonalar. Kamera ulanish sozlamalariga (IP, RTSP,")
    print("login/parol) ular tega olmaydi.")
    print("Parollar boshqa hech qayerda saqlanmaydi — shu chiqishdan oling.")


if __name__ == "__main__":
    requested = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    login_prefix = sys.argv[2] if len(sys.argv) > 2 else "kamera"
    asyncio.run(main(requested, login_prefix))
