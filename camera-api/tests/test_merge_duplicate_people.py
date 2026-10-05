"""Dublikatlarni birlashtirish.

Skript odam yozuvini O'CHIRADI, shuning uchun eng muhim shartlar:
yuzi tasdiqlangan yozuv va uning identifikatori saqlanishi, hech qanday
davomat yoki dars bog'lanishi yo'qolmasligi, noaniq juftliklar faqat
aniq ruxsat (--qisman) bilan birlashtirilishi, va bir xil ism-familiyali
BOSHQA odamlarning hech qachon qo'shilib ketmasligi.
"""

from datetime import date

import pytest
from sqlalchemy import func, select

from app.models import AttendanceRecord, AuditLog, Faculty, LessonAttendance, LessonSession, StudentStaff
from scripts.merge_duplicate_people import name_key, name_tokens, names_match, run, run_pair
from tests.conftest import TestSessionLocal


def _imported(name, pinfl, faculty_id, unit="Biotibbiyot muhandisligi kafedrasi", type="xodim", confirmed=False):
    record = StudentStaff(full_name=name, type=type, pinfl=pinfl, faculty_id=faculty_id,
                          group_or_position=unit, biometrics_status="yoq")
    if confirmed:
        record.biometrics_status = "tasdiqlangan"
        record.biometric_embedding = "[0.2]"
    return record


def _manual(name, unit="Katta o'qituvchi", type="xodim"):
    return StudentStaff(full_name=name, type=type, group_or_position=unit,
                        biometrics_status="tasdiqlangan", biometric_embedding="[0.1]",
                        biometric_photo_key="biometrics/face.jpg")


@pytest.fixture
async def faculty(db_session, seeded) -> Faculty:
    return (await db_session.execute(select(Faculty).limit(1))).scalar_one()


async def _people(db_session) -> list[StudentStaff]:
    db_session.expire_all()
    return list((await db_session.execute(select(StudentStaff).order_by(StudentStaff.full_name))).scalars().all())


class TestNameMatching:
    def test_exact_key_ignores_case_spacing_and_apostrophe_style(self):
        assert name_key("G‘aniyev  Aziz O‘G‘LI") == name_key("g'aniyev aziz o'g'li")

    @pytest.mark.parametrize(
        ("typed", "official"),
        [
            ("Ismoilov Sanjarbek Salohiddin o'g'li", "Ismoilov Sanjarbek Saloxiddin o'g'li"),
            ("Saydullaeva Kamila Mirshodovna", "Saydullayeva Kamila Mirshodovna"),
            ("Arslonbek Ikromiy Ilxomjon o‘g‘li", "Ikromiy Arslonbek Ilxomjon o'g'li"),
            ("Махаматова Умидахон Рахмонжоновна", "Maxamatova Umidaxon Raxmonjonovna"),
            ("Kurbonova Aziza", "Kurbonova Aziza Anvarovna"),
            ("Mamadaliyev Nemat Qaxorovich", "Mamadaliyev Nemat Koxorovich"),
            ("Imomov Farxodjon Toshqo 'ziyevich", "Imomov Farxodjon Toshkuziyevich"),
            ("Xaydarov Axrorjon Gayratjonb ogli", "Xaydarov Axrorjon G'ayratjon o'g'li"),
        ],
    )
    def test_same_person_written_differently(self, typed, official):
        assert names_match(name_tokens(typed), name_tokens(official))

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ("Karimov Aziz Olimovich", "Karimov Aziz Botirovich"),  # boshqa ota — boshqa odam
            ("Karimov Aziz Olimovich", "Karimov Anvar Olimovich"),  # boshqa ism
            ("Karimova Aziza", "Rahimova Aziza"),  # boshqa familiya
            ("Yigitaliyeva", "Yigitaliyeva Nodira"),  # bitta so'z — moslab bo'lmaydi
            # Otasining ismi yo'q — familiyadagi har qanday farq boshqa odam bo'lishi mumkin
            ("Ismoiljanova Nilufar", "Ismoilova Nilufar Ikrom qizi"),
            ("Kurbonova Aziza", "Qurbonboyeva Aziza Muzaffar qizi"),
        ],
    )
    def test_different_people_never_match(self, a, b):
        assert not names_match(name_tokens(a), name_tokens(b))


class TestExactMerge:
    async def test_the_confirmed_record_keeps_its_face_and_receives_the_imported_data(self, db_session, faculty):
        source = _imported("Nosirov Nodirbek Valijonovich", "30000000000047", faculty.id)
        keep = _manual("Nosirov Nodirbek Valijonovich")
        db_session.add_all([source, keep])
        await db_session.commit()
        keep_id = keep.id

        plan = await run(session_factory=TestSessionLocal)
        assert len(plan.pairs) == 1

        (person,) = await _people(db_session)
        assert person.id == keep_id
        assert person.pinfl == "30000000000047"
        assert person.faculty_id == faculty.id
        assert person.group_or_position == "Biotibbiyot muhandisligi kafedrasi"
        assert person.biometric_embedding == "[0.1]"

        audit = (await db_session.execute(select(AuditLog).where(AuditLog.user_name == "Dublikatlarni birlashtirish"))).scalars().all()
        assert len(audit) == 1
        assert "30000000000047" not in audit[0].action

    async def test_links_to_the_removed_copy_move_to_the_kept_record(self, db_session, faculty):
        source = _imported("Gasanova Nigora Muxtorovna", "40000000000037", faculty.id)
        keep = _manual("Gasanova Nigora Muxtorovna", unit="Assistent")
        db_session.add_all([source, keep])
        await db_session.flush()

        lesson = LessonSession(date=date(2026, 9, 14), group_name="DI-1625", faculty="Davolash ishi",
                               teacher="Gasanova N.", subject="Biofizika", attention_score=0,
                               teacher_activity_score=0, teacher_id=source.id)
        other_lesson = LessonSession(date=date(2026, 9, 14), group_name="DI-1626", faculty="Davolash ishi",
                                     teacher="Gasanova N.", subject="Biofizika", attention_score=0,
                                     teacher_activity_score=0)
        db_session.add_all([lesson, other_lesson])
        await db_session.flush()
        db_session.add_all([
            AttendanceRecord(student_staff_id=source.id, date=date(2026, 9, 12), status="keldi"),
            AttendanceRecord(student_staff_id=source.id, date=date(2026, 9, 13), status="kech_keldi"),
            AttendanceRecord(student_staff_id=keep.id, date=date(2026, 9, 13), status="keldi"),
            LessonAttendance(lesson_session_id=other_lesson.id, student_staff_id=source.id, sightings=4),
        ])
        await db_session.commit()
        keep_id, lesson_id = keep.id, lesson.id

        await run(session_factory=TestSessionLocal)
        db_session.expire_all()

        rows = (await db_session.execute(select(AttendanceRecord))).scalars().all()
        assert {r.date: r.status for r in rows} == {date(2026, 9, 12): "keldi", date(2026, 9, 13): "keldi"}
        assert all(r.student_staff_id == keep_id for r in rows)
        assert (await db_session.execute(select(LessonAttendance))).scalar_one().student_staff_id == keep_id
        assert (await db_session.get(LessonSession, lesson_id)).teacher_id == keep_id

    async def test_dry_run_changes_nothing(self, db_session, faculty):
        db_session.add_all([_imported("Nosirov Nodirbek Valijonovich", "30000000000047", faculty.id),
                            _manual("Nosirov Nodirbek Valijonovich")])
        await db_session.commit()
        plan = await run(dry_run=True, session_factory=TestSessionLocal)
        assert len(plan.pairs) == 1
        assert len(await _people(db_session)) == 2

    async def test_second_run_finds_nothing(self, db_session, faculty):
        db_session.add_all([_imported("Nosirov Nodirbek Valijonovich", "30000000000047", faculty.id),
                            _manual("Nosirov Nodirbek Valijonovich")])
        await db_session.commit()
        await run(session_factory=TestSessionLocal)
        plan = await run(session_factory=TestSessionLocal)
        assert plan.pairs == [] and plan.partial == []
        assert len(await _people(db_session)) == 1


class TestPartialMerge:
    async def test_partial_pairs_wait_for_explicit_permission(self, db_session, faculty):
        db_session.add_all([
            _imported("Ismoilov Sanjarbek Saloxiddin o'g'li", "30000000000061", faculty.id),
            _manual("Ismoilov Sanjarbek Salohiddin o'g'li", unit="Tizim administratori"),
        ])
        await db_session.commit()

        plan = await run(session_factory=TestSessionLocal)
        assert len(plan.partial) == 1
        assert len(await _people(db_session)) == 2  # --qisman berilmagan

        await run(include_partial=True, session_factory=TestSessionLocal)
        (person,) = await _people(db_session)
        assert person.pinfl == "30000000000061"
        assert person.biometric_embedding == "[0.1]"
        assert person.full_name == "Ismoilov Sanjarbek Saloxiddin o'g'li"

    async def test_when_both_records_are_confirmed_the_official_one_stays(self, db_session, faculty):
        official = _imported("Oribjonova Hadisaxon Abdumutallib qizi", "40000000000029", faculty.id,
                             unit="Gospital terapiya (laboratoriya)", confirmed=True)
        manual = _manual("Oribjonova Hadisaxon Abdumutalib qizi", unit="Assistent")
        db_session.add_all([official, manual])
        await db_session.flush()
        db_session.add(AttendanceRecord(student_staff_id=manual.id, date=date(2026, 9, 11), status="keldi"))
        await db_session.commit()
        official_id = official.id

        plan = await run(include_partial=True, session_factory=TestSessionLocal)
        assert [p.kind for p in plan.partial] == ["ikkalasi_tasdiqlangan"]

        (person,) = await _people(db_session)
        assert person.id == official_id
        assert person.pinfl == "40000000000029"
        assert person.group_or_position == "Gospital terapiya (laboratoriya)"
        assert (await db_session.execute(select(AttendanceRecord))).scalar_one().student_staff_id == official_id


class TestManualPair:
    async def test_two_confirmed_manual_copies_then_the_official_record(self, db_session, faculty):
        """Yusupov holati: qo'lda ikki marta qo'shilgan + import qilingan.
        Avval admin keraksiz nusxani ko'rsatadi, qolgani oddiy ishga tushirishda birlashadi."""
        official = _imported("Yusupov Abdulaziz Adxamjonovich", "30000000000071", faculty.id, unit="Anatomiya")
        older = _manual("Yusupov Abdulaziz Adxamjonovich", unit="Tyutor")
        newer = _manual("Yusupov Abdulaziz Adxamjonovich", unit="Tyutor")
        db_session.add_all([official, older, newer])
        await db_session.commit()
        newer_id = newer.id

        pair = await run_pair(str(newer.id)[:8], str(older.id)[:8], session_factory=TestSessionLocal)
        assert pair.take_identity is False
        assert len(await _people(db_session)) == 2

        plan = await run(session_factory=TestSessionLocal)
        assert len(plan.pairs) == 1
        (person,) = await _people(db_session)
        assert person.id == newer_id
        assert person.pinfl == "30000000000071"

    async def test_manual_pair_takes_the_pinfl_when_the_kept_record_has_none(self, db_session, faculty):
        official = _imported("Xaydarov Voxidjon Obitovich", "30000000000017", faculty.id)
        manual = _manual("Xaydarov Voxidjon Obitovich", unit="Tyutor")
        db_session.add_all([official, manual])
        await db_session.commit()
        pair = await run_pair(str(manual.id)[:8], str(official.id)[:8], session_factory=TestSessionLocal)
        assert pair.take_identity is True
        (person,) = await _people(db_session)
        assert person.pinfl == "30000000000017"

    async def test_manual_pair_dry_run_changes_nothing(self, db_session, faculty):
        a, b = _manual("Aliyev Vali"), _manual("Aliyev Vali")
        db_session.add_all([a, b])
        await db_session.commit()
        await run_pair(str(a.id)[:8], str(b.id)[:8], dry_run=True, session_factory=TestSessionLocal)
        assert len(await _people(db_session)) == 2

    async def test_staff_and_student_are_refused(self, db_session, faculty):
        a = _manual("Aliyev Vali")
        b = _imported("Aliyev Vali", "60000000000099", faculty.id, type="talaba")
        db_session.add_all([a, b])
        await db_session.commit()
        with pytest.raises(SystemExit):
            await run_pair(str(a.id)[:8], str(b.id)[:8], session_factory=TestSessionLocal)
        assert len(await _people(db_session)) == 2


class TestSameTypePreference:
    async def test_a_student_namesake_does_not_block_the_staff_match(self, db_session, faculty):
        db_session.add_all([
            _manual("Kurbonova Aziza Anvarovna"),
            _imported("Kurbonova Aziza Anvarovna", "40000000000013", faculty.id, unit="Laboratoriya",
                      confirmed=True),
            _imported("Kurbonova Aziza Anvar qizi", "60000000000071", faculty.id, unit="3-kurs", type="talaba"),
        ])
        await db_session.commit()
        plan = await run(include_partial=True, session_factory=TestSessionLocal)
        assert [p.kind for p in plan.partial] == ["ikkalasi_tasdiqlangan"]
        assert plan.ambiguous == []


class TestSuspiciousCasesAreLeftAlone:
    async def test_two_imported_namesakes_are_not_guessed(self, db_session, faculty):
        db_session.add_all([
            _imported("Karimov Aziz Olimovich", "30000000000001", faculty.id),
            _imported("Karimov Aziz Olimovich", "30000000000002", faculty.id, unit="Anatomiya"),
            _manual("Karimov Aziz Olimovich"),
        ])
        await db_session.commit()
        plan = await run(include_partial=True, session_factory=TestSessionLocal)
        assert plan.pairs == [] and plan.partial == []
        assert len(plan.ambiguous) == 1
        assert len(await _people(db_session)) == 3

    async def test_two_confirmed_manual_copies_are_not_guessed(self, db_session, faculty):
        db_session.add_all([
            _imported("Yusupov Abdulaziz Adxamjonovich", "30000000000071", faculty.id),
            _manual("Yusupov Abdulaziz Adxamjonovich", unit="Tyutor"),
            _manual("Yusupov Abdulaziz Adxamjonovich", unit="Tyutor"),
        ])
        await db_session.commit()
        plan = await run(include_partial=True, session_factory=TestSessionLocal)
        assert plan.pairs == [] and plan.partial == []
        assert len(plan.ambiguous) == 1
        assert len(await _people(db_session)) == 3

    async def test_a_namesake_with_another_father_is_not_merged(self, db_session, faculty):
        db_session.add_all([
            _imported("Karimov Aziz Olimovich", "30000000000001", faculty.id),
            _manual("Karimov Aziz Botirovich"),
        ])
        await db_session.commit()
        plan = await run(include_partial=True, session_factory=TestSessionLocal)
        assert plan.partial == []
        assert len(plan.not_found) == 1
        assert len(await _people(db_session)) == 2

    async def test_a_student_and_a_staff_member_are_never_merged(self, db_session, faculty):
        db_session.add_all([
            _imported("Rahimova Dilnoza Oybek qizi", "60000000000011", faculty.id, unit="2-kurs, DI-1625",
                      type="talaba"),
            _manual("Rahimova Dilnoza Oybek qizi"),
        ])
        await db_session.commit()
        plan = await run(include_partial=True, session_factory=TestSessionLocal)
        assert plan.pairs == [] and plan.partial == []
        assert len(plan.cross_type) == 1
        assert len(await _people(db_session)) == 2

    async def test_a_single_word_name_is_reported(self, db_session, faculty):
        db_session.add_all([_imported("Yigitaliyeva Nodira Ahmadovna", "40000000000081", faculty.id),
                            _manual("Yigitaliyeva")])
        await db_session.commit()
        plan = await run(include_partial=True, session_factory=TestSessionLocal)
        assert len(plan.incomplete) == 1
        assert len(await _people(db_session)) == 2

    async def test_two_real_people_with_their_own_pinfl_are_untouched(self, db_session, faculty):
        confirmed_with_pinfl = _manual("Aliyev Vali Karimovich")
        confirmed_with_pinfl.pinfl = "30000000000009"
        db_session.add_all([confirmed_with_pinfl,
                            _imported("Aliyev Vali Karimovich", "30000000000010", faculty.id)])
        await db_session.commit()
        await run(include_partial=True, session_factory=TestSessionLocal)
        assert await db_session.scalar(select(func.count()).select_from(StudentStaff)) == 2
