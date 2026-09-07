"""Import skripti 688 ta xodimni bazaga kiritadi va uni istalgan payt
qayta ishga tushirish mumkin bo'lishi kerak.

Ikkinchi shart birinchisidan muhimroq. Skript serverda qo'lda ishga
tushiriladi, ya'ni uni ikki marta bosib yuborish yoki ro'yxat
yangilanganda qayta ishlatish tabiiy holat. Agar u shunda takroriy
qatorlar yaratsa yoki allaqachon yuzini tasdiqlagan xodimning
tasdig'ini o'chirsa — bu odamlarni qaytadan ro'yxatdan o'tishga
majburlardi.
"""

import pytest
from sqlalchemy import func, select

from app.models import Faculty, StudentStaff
from scripts.import_xodimlar import XODIMLAR, _fac_key, run
from tests.conftest import TestSessionLocal


class TestTheDataItself:
    def test_every_pinfl_is_unique(self):
        """Takroriy raqam bazadagi unikal cheklovga urilib, importni
        yarim yo'lda to'xtatib qo'yardi."""
        assert len({p for p, _, _, _ in XODIMLAR}) == len(XODIMLAR)

    def test_nobody_is_missing_a_name(self):
        assert all(name.strip() for _, name, _, _ in XODIMLAR)

    def test_every_person_has_a_unit(self):
        """Kafedra yoki bo'lim — StudentStaff.group_or_position uchun
        majburiy maydon."""
        assert all(unit.strip() for _, _, _, unit in XODIMLAR)

    def test_names_are_not_left_in_capitals(self):
        """Manba faylda ismlar BOSH HARFLAR bilan. Ular shu holicha
        qolsa, panelda ham, hodisa yozuvlarida ham baqirib turardi."""
        assert not any(name.isupper() for _, name, _, _ in XODIMLAR)

    def test_placeholder_values_are_not_part_of_a_name(self):
        """Manba faylda otasining ismi yoki familiya o'rnida "XXX"
        uchraydi — u ismning bir qismi emas."""
        assert not any("Xxx" in name or "XXX" in name for _, name, _, _ in XODIMLAR)


class TestFacultyMatching:
    def test_the_word_fakulteti_does_not_split_one_faculty_in_two(self):
        assert _fac_key("Davolash ishi fakulteti") == _fac_key("Davolash ishi")
        assert _fac_key("Xalqaro fakultet") == _fac_key("Xalqaro")

    def test_genuinely_different_faculties_stay_apart(self):
        assert _fac_key("Tibbiy profilaktika va jamoat salomatligi fakulteti") != _fac_key(
            "Jamoat salomatligi"
        )


@pytest.mark.usefixtures("seeded")
class TestImportRun:
    async def test_every_person_in_the_list_reaches_the_database(self, db_session):
        await run(session_factory=TestSessionLocal)
        total = await db_session.scalar(
            select(func.count()).select_from(StudentStaff).where(StudentStaff.pinfl.is_not(None))
        )
        assert total == len(XODIMLAR)

    async def test_running_twice_does_not_duplicate_anyone(self, db_session):
        await run(session_factory=TestSessionLocal)
        first = await db_session.scalar(select(func.count()).select_from(StudentStaff))
        await run(session_factory=TestSessionLocal)
        second = await db_session.scalar(select(func.count()).select_from(StudentStaff))
        assert first == second

    async def test_a_confirmed_face_survives_a_second_run(self, db_session):
        """Eng muhim shart: skriptni qayta ishga tushirish yuzini
        tasdiqlagan xodimni ro'yxatdan chiqarib yubormasligi kerak."""
        await run(session_factory=TestSessionLocal)
        pinfl = XODIMLAR[0][0]
        record = (
            await db_session.execute(select(StudentStaff).where(StudentStaff.pinfl == pinfl))
        ).scalar_one()
        record.biometrics_status = "tasdiqlangan"
        record.biometric_embedding = "[0.1, 0.2]"
        await db_session.commit()

        await run(session_factory=TestSessionLocal)

        await db_session.refresh(record)
        assert record.biometrics_status == "tasdiqlangan"
        assert record.biometric_embedding == "[0.1, 0.2]"

    async def test_an_existing_faculty_is_reused_and_renamed(self, db_session):
        """Seed dagi qisqa nom kadrlar ro'yxatidagi rasmiy nomga
        aylanadi, lekin QATOR o'sha qoladi — unga bog'langan talabalar
        va guruhlar yo'qolmaydi."""
        # "Davolash ishi" seed fixture'da allaqachon yaratilgan —
        # aynan shu holat tekshiriladi.
        before = (
            await db_session.execute(select(Faculty).where(Faculty.name == "Davolash ishi"))
        ).scalar_one()
        before_id = before.id

        await run(session_factory=TestSessionLocal)

        after = (
            await db_session.execute(
                select(Faculty).where(Faculty.name == "Davolash ishi fakulteti")
            )
        ).scalar_one()
        assert after.id == before_id

    async def test_people_without_a_faculty_are_still_imported(self, db_session):
        """Rektorat, texnik va xo'jalik bo'limlari xodimlarining
        fakulteti yo'q. Ularni tashlab ketish "hech qaysi xodim qolib
        ketmasin" talabini buzardi."""
        await run(session_factory=TestSessionLocal)
        expected = sum(1 for _, _, fac, _ in XODIMLAR if not fac)
        actual = await db_session.scalar(
            select(func.count())
            .select_from(StudentStaff)
            .where(StudentStaff.pinfl.is_not(None))
            .where(StudentStaff.faculty_id.is_(None))
        )
        assert actual == expected
        assert expected > 0

    async def test_everyone_starts_without_biometrics(self, db_session):
        """Import faqat shaxs ma'lumotini kiritadi — yuz keyin, odamning
        o'zi tomonidan qo'shiladi."""
        await run(session_factory=TestSessionLocal)
        confirmed = await db_session.scalar(
            select(func.count())
            .select_from(StudentStaff)
            .where(StudentStaff.pinfl.is_not(None))
            .where(StudentStaff.biometrics_status != "yoq")
        )
        assert confirmed == 0
