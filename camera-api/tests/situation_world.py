"""Situatsion markaz testlari uchun umumiy "kichik institut".

Har test shu dunyoni quradi va javoblarni qo'lda hisoblangan sonlar
bilan solishtiradi. Sonlar izohlarda — o'zgartirsangiz, testlardagi
kutilgan qiymatlarni ham yangilang.

Talabalar (faol, 12 ta):
  Davolash ishi
    "2-kurs, DI-2301": Aliyev (tasdiq., keldi 08:05), Botirova (tasdiq., kech_keldi 09:15),
                       Choriyev (tasdiq., kelmadi), Davronov (tasdiq., yozuv yo'q),
                       Ergasheva (tasdiqlanmagan, yozuv yo'q)
                       + nofaol Faol-emas (hisobga kirmaydi)
    "2-kurs, DI-2302": Fayziyev (tasdiq., keldi 08:30)
    "3-kurs, DI-2101": G'aniyev (tasdiq., keldi 08:10)
    "4-kurs"         : Hamidov (tasdiq., keldi 08:20) — guruhsiz, faqat kurs jamida
  Pediatriya
    "1-kurs, PE-2501": Ismoilova (tasdiq., keldi 08:45), Jo'rayev (tasdiq., kelmadi)
    "2-kurs, XDI-2301": Komilov (tasdiqlanmagan) — "%DI-2301" LIKE ga tushadi, lekin a'zo emas
  Fakultetsiz
    "1-kurs, XX-1": Latipov (tasdiqlanmagan)

Xodimlar (faol, 4 ta):
  "Anatomiya kafedrasi"          Yusupova (tasdiq., keldi 07:55-17:00)
  "  anatomiya   KAFEDRASI "     Karimov (tasdiq., kech_keldi 09:20)
  "Fiziologiya kafedrasi"        Rahimov (tasdiq., yozuv yo'q)
  "Bosh hisobchi"                Qodirova (tasdiqlanmagan) -> sof lavozim: "Lavozim bo'yicha"
  + nofaol Nofaol-xodim ("Anatomiya kafedrasi")

Bugungi darslar (davomiylik 80 daq., kechikish chegarasi 5 daq.):
  L1 DI-2301 Anatomiya   Yusupova  205  now-3h  tugagan, on_time=True, diqqat 80, faollik 70, yakunlangan
  L2 DI-2301 Fiziologiya Rahimov   310  now-30m davom etmoqda, on_time=False -> kechikdi
  L3 DI-2302 Anatomiya   Karimov   205  now+2h  boshlanmagan -> kutilmoqda
  L4 PE-2501 Anatomiya   Karimov   205  now-5h  tugagan, tashrif start+15 -> kechikdi, diqqat 60
  L5 DI-2101 Gistologiya "Soatov B." (teacher_id yo'q) 310 now-4h -> nomalum
  L6 DI-2302 Fiziologiya Rahimov   310  now-6h  tugagan, on_time=False, tashrif yo'q -> kelmadi
Kechagi dars:
  LY DI-2301 Anatomiya Yusupova 205 kecha 10:00, on_time=False -> kelmadi
"""

from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import (
    AIModuleConfig,
    AttendanceRecord,
    Building,
    Camera,
    Department,
    Event,
    Faculty,
    LessonAttendance,
    LessonSession,
    PresenceVisit,
    StudentGroup,
    StudentStaff,
)
from app.services import situation
from app.timezone import INSTITUTE_TZ


@pytest.fixture(autouse=True)
def _situation_settings(monkeypatch):
    monkeypatch.setattr(settings, "lesson_duration_minutes", 80)
    monkeypatch.setattr(settings, "attendance_late_to_lesson_grace_minutes", 5)
    monkeypatch.setattr(settings, "lesson_attendance_min_sightings", 3)
    situation.clear_cache()
    yield
    situation.clear_cache()


def _person(name, type_, unit, *, faculty=None, enrolled=True, active=True, photo=None):
    return StudentStaff(
        full_name=name, type=type_, group_or_position=unit, faculty_id=faculty.id if faculty else None,
        biometrics_status="tasdiqlangan" if enrolled else "yoq", active=active, biometric_photo_key=photo,
    )


def _record(person, day, status, check_in=None, check_out=None):
    return AttendanceRecord(
        student_staff_id=person.id, date=day, status=status,
        check_in=time.fromisoformat(check_in) if check_in else None,
        check_out=time.fromisoformat(check_out) if check_out else None,
        source="kamera",
    )


def _lesson(day, start, group, subject, faculty, teacher_name, *, teacher=None, camera=None, on_time=None,
            attention=(0, 0), activity=(0, 0)):
    return LessonSession(
        date=day, group_name=group, faculty=faculty, teacher=teacher_name,
        teacher_id=teacher.id if teacher else None, subject=subject,
        attention_score=attention[0], attention_samples=attention[1],
        teacher_activity_score=activity[0], activity_samples=activity[1],
        sleep_incidents=0, teacher_on_time=on_time, camera_id=camera.id if camera else None,
        scheduled_start_time=start,
    )


@pytest.fixture
async def world(db_session, seeded):
    db = db_session
    now = datetime.now(INSTITUTE_TZ).replace(microsecond=0)
    today = now.date()
    yesterday = today - timedelta(days=1)

    faculties = {f.name: f for f in (await db.execute(select(Faculty))).scalars().all()}
    di, pe = faculties["Davolash ishi"], faculties["Pediatriya"]
    building = (await db.execute(select(Building).order_by(Building.sort_order))).scalars().first()

    utc_now = datetime.now(timezone.utc)
    room205 = Camera(name="205-xona", ip="10.9.0.5", building_id=building.id, zone="205-xona", resolution="1080p",
                     status="faol", last_seen_at=utc_now, last_frame_at=utc_now)
    room310 = Camera(name="310-xona", ip="10.9.0.10", building_id=building.id, zone="310-xona", resolution="1080p",
                     status="faol", last_seen_at=utc_now)
    entrance = Camera(name="Kirish-1", ip="10.9.0.1", building_id=building.id, zone="Asosiy kirish",
                      resolution="1080p", status="nofaol", is_entrance=True)
    anatomy = Department(name="Anatomiya kafedrasi", building_id=building.id)
    physiology = Department(name="Fiziologiya kafedrasi", building_id=None)
    db.add_all([room205, room310, entrance, anatomy, physiology])
    db.add_all([
        StudentGroup(name="DI-2301", faculty_id=di.id, course=2, student_count=5),
        StudentGroup(name="DI-2303", faculty_id=di.id, course=2, student_count=0),
    ])

    s = SimpleNamespace()
    s.aliyev = _person("Aliyev Anvar", "talaba", "2-kurs, DI-2301", faculty=di, photo="faces/aliyev.jpg")
    s.botirova = _person("Botirova Nigora", "talaba", "2-kurs, DI-2301", faculty=di)
    s.choriyev = _person("Choriyev Sardor", "talaba", "2-kurs, DI-2301", faculty=di)
    s.davronov = _person("Davronov Jasur", "talaba", "2-kurs, DI-2301", faculty=di)
    s.ergasheva = _person("Ergasheva Laylo", "talaba", "2-kurs, DI-2301", faculty=di, enrolled=False)
    s.inactive_student = _person("Faol-emas Talaba", "talaba", "2-kurs, DI-2301", faculty=di, active=False)
    s.fayziyev = _person("Fayziyev Otabek", "talaba", "2-kurs, DI-2302", faculty=di)
    s.ganiyev = _person("G'aniyev Sherzod", "talaba", "3-kurs, DI-2101", faculty=di)
    s.hamidov = _person("Hamidov Rustam", "talaba", "4-kurs", faculty=di)
    s.ismoilova = _person("Ismoilova Madina", "talaba", "1-kurs, PE-2501", faculty=pe)
    s.jorayev = _person("Jo'rayev Ulug'bek", "talaba", "1-kurs, PE-2501", faculty=pe)
    s.komilov = _person("Komilov Doniyor", "talaba", "2-kurs, XDI-2301", faculty=pe, enrolled=False)
    s.latipov = _person("Latipov Akmal", "talaba", "1-kurs, XX-1", enrolled=False)

    s.yusupova = _person("Yusupova Dilnoza Anvarovna", "xodim", "Anatomiya kafedrasi", photo="faces/yusupova.jpg")
    s.karimov = _person("Karimov Aziz Olimovich", "xodim", "  anatomiya   KAFEDRASI ")
    s.rahimov = _person("Rahimov Bobur", "xodim", "Fiziologiya kafedrasi")
    s.qodirova = _person("Qodirova Malika", "xodim", "Bosh hisobchi", enrolled=False)
    s.inactive_staff = _person("Nofaol-xodim", "xodim", "Anatomiya kafedrasi", active=False)
    people = [v for v in vars(s).values()]
    db.add_all(people)
    await db.flush()

    db.add_all([
        _record(s.aliyev, today, "keldi", "08:05"),
        _record(s.botirova, today, "kech_keldi", "09:15"),
        _record(s.choriyev, today, "kelmadi"),
        _record(s.fayziyev, today, "keldi", "08:30"),
        _record(s.ganiyev, today, "keldi", "08:10"),
        _record(s.hamidov, today, "keldi", "08:20"),
        _record(s.ismoilova, today, "keldi", "08:45"),
        _record(s.jorayev, today, "kelmadi"),
        _record(s.inactive_student, today, "keldi", "08:00"),
        _record(s.yusupova, today, "keldi", "07:55", "17:00"),
        _record(s.karimov, today, "kech_keldi", "09:20"),
        # kecha
        _record(s.aliyev, yesterday, "keldi", "08:15"),
        _record(s.botirova, yesterday, "kelmadi"),
        _record(s.choriyev, yesterday, "kelmadi"),
        _record(s.yusupova, yesterday, "keldi", "08:00"),
    ])

    minutes = lambda m: timedelta(minutes=m)  # noqa: E731
    l1 = _lesson(today, now - minutes(180), "DI-2301", "Anatomiya", "Davolash ishi", "Yusupova D.",
                 teacher=s.yusupova, camera=room205, on_time=True, attention=(80, 3), activity=(70, 2))
    l2 = _lesson(today, now - minutes(30), "DI-2301", "Fiziologiya", "Davolash ishi", "Rahimov B.",
                 teacher=s.rahimov, camera=room310, on_time=False)
    l3 = _lesson(today, now + minutes(120), "DI-2302", "Anatomiya", "Davolash ishi", "Karimov A.",
                 teacher=s.karimov, camera=room205)
    l4 = _lesson(today, now - minutes(300), "PE-2501", "Anatomiya", "Pediatriya", "Karimov A.",
                 teacher=s.karimov, camera=room205, attention=(60, 1))
    l5 = _lesson(today, now - minutes(240), "DI-2101", "Gistologiya", "Davolash ishi", "Soatov B.",
                 camera=room310)
    l6 = _lesson(today, now - minutes(360), "DI-2302", "Fiziologiya", "Davolash ishi", "Rahimov B.",
                 teacher=s.rahimov, camera=room310, on_time=False)
    ly = _lesson(yesterday, datetime.combine(yesterday, time(10, 0), tzinfo=INSTITUTE_TZ), "DI-2301",
                 "Anatomiya", "Davolash ishi", "Yusupova D.", teacher=s.yusupova, camera=room205, on_time=False)
    db.add_all([l1, l2, l3, l4, l5, l6, ly])
    await db.flush()

    db.add_all([
        # L1 yakunlangan
        LessonAttendance(lesson_session_id=l1.id, student_staff_id=s.aliyev.id, sightings=6,
                         first_seen_at=l1.scheduled_start_time + minutes(1), status="keldi"),
        LessonAttendance(lesson_session_id=l1.id, student_staff_id=s.botirova.id, sightings=4,
                         first_seen_at=l1.scheduled_start_time + minutes(14), status="kech_keldi"),
        LessonAttendance(lesson_session_id=l1.id, student_staff_id=s.choriyev.id, sightings=0, status="kelmadi"),
        LessonAttendance(lesson_session_id=l1.id, student_staff_id=s.davronov.id, sightings=0, status="kelmadi"),
        # L2 davom etmoqda — status hali yo'q
        LessonAttendance(lesson_session_id=l2.id, student_staff_id=s.aliyev.id, sightings=5,
                         first_seen_at=l2.scheduled_start_time + minutes(1)),
        LessonAttendance(lesson_session_id=l2.id, student_staff_id=s.botirova.id, sightings=4,
                         first_seen_at=l2.scheduled_start_time + minutes(12)),
        LessonAttendance(lesson_session_id=l2.id, student_staff_id=s.davronov.id, sightings=1,
                         first_seen_at=l2.scheduled_start_time + minutes(2)),
        # Karimov L4 xonasiga 15 daqiqa kech kirdi
        PresenceVisit(student_staff_id=s.karimov.id, camera_id=room205.id,
                      first_seen_at=l4.scheduled_start_time + minutes(15),
                      last_seen_at=l4.scheduled_start_time + minutes(60), sightings=20),
        # Aliyev kirish eshigida
        PresenceVisit(student_staff_id=s.aliyev.id, camera_id=entrance.id,
                      first_seen_at=datetime.combine(today, time(8, 5), tzinfo=INSTITUTE_TZ),
                      last_seen_at=datetime.combine(today, time(8, 7), tzinfo=INSTITUTE_TZ), sightings=3),
    ])

    module = (await db.execute(select(AIModuleConfig).order_by(AIModuleConfig.code))).scalars().first()

    def event(severity, status, *, due=None, trial=False):
        return Event(camera_name="205-xona", building=building.name, module_code=module.code,
                     module_name=module.name, group="test", confidence=90, severity=severity, status=status,
                     occurred_at=utc_now, due_at=due, is_trial=trial)

    db.add_all([
        event("yuqori", "yangi", due=utc_now - timedelta(minutes=10)),  # ochiq, yuqori, muddati o'tgan
        event("past", "jarayonda"),
        event("o'rta", "rad_etilgan"),
        event("yuqori", "yangi", trial=True),  # sinov — hisobga kirmaydi
    ])
    await db.commit()

    return SimpleNamespace(
        now=now, today=today, yesterday=yesterday, di=di, pe=pe, building=building,
        room205=room205, room310=room310, entrance=entrance, anatomy=anatomy, physiology=physiology,
        people=s, l1=l1, l2=l2, l3=l3, l4=l4, l5=l5, l6=l6, ly=ly,
    )
