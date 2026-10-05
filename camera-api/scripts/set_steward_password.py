"""Kamera mas'uli hisoblariga bitta umumiy parol qo'yadi.

Serverda:
    cd /opt/camera/camera-api
    docker compose -f docker-compose.yml -f docker-compose.override.yml \
        exec -T api python scripts/set_steward_password.py 12345678

Ixtiyoriy ikkinchi argument — login prefiksi (standart "kamera"), ya'ni
faqat kamera1..kameraN hisoblariga tegadi. Prefiks o'rniga "*" berilsa,
roli "kamera-masuli" bo'lgan BARCHA hisoblarga qo'llanadi.

Parol o'zgargach eski sessiyalar bekor qilinadi (token_version oshadi),
ya'ni o'sha hisob bilan ochiq turgan brauzerlar qaytadan kirishi kerak.

Xavfsizlik eslatmasi: bir xil va oddiy parol — bir odam bilsa, hammasi
bilingani. Bu hisoblar kamera ma'lumotlarini o'zgartiradi va monitoring
devorini ko'radi, shuning uchun vaqtinchalik yechim sifatida ishlating;
keyinroq shu skriptning o'zi bilan kuchliroq parolga o'ting.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402
from app.security import hash_password  # noqa: E402

ROLE = "kamera-masuli"
MIN_LENGTH = 8


async def main(password: str, prefix: str) -> None:
    async with SessionLocal() as db:
        stmt = select(User).where(User.role == ROLE).order_by(User.login)
        if prefix != "*":
            stmt = stmt.where(User.login.like(f"{prefix}%"))
        users = (await db.execute(stmt)).scalars().all()
        if not users:
            print(f"'{ROLE}' rolida '{prefix}' bilan boshlanadigan hisob topilmadi.")
            return

        digest = hash_password(password)
        for user in users:
            user.password_hash = digest
            # Eski JWT'lar yaroqsiz bo'lsin — parol o'zgardi.
            user.token_version += 1
        await db.commit()

        print()
        print("=" * 64)
        print("PAROL YANGILANDI")
        print("=" * 64)
        print("login | parol | ism")
        for user in users:
            print(f"{user.login} | {password} | {user.full_name}")
        print()
        print(f"Jami {len(users)} ta hisob. Ochiq sessiyalar bekor qilindi —")
        print("bu hisoblar bilan qaytadan kirish kerak.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Foydalanish: python scripts/set_steward_password.py <parol> [login-prefiksi|*]")
        raise SystemExit(2)
    new_password = sys.argv[1]
    if len(new_password) < MIN_LENGTH:
        print(f"Parol kamida {MIN_LENGTH} belgi bo'lishi kerak.")
        raise SystemExit(2)
    login_prefix = sys.argv[2] if len(sys.argv) > 2 else "kamera"
    asyncio.run(main(new_password, login_prefix))
