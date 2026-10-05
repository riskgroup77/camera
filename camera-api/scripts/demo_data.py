"""Lokal ko'rib chiqish uchun sintetik ma'lumotlar (faqat camera_api_dev bazasi).

Hech qanday haqiqiy shaxs ma'lumoti yo'q — ismlar tasodifiy birikma.
"""

import asyncio
import json
import random
import uuid
from datetime import date, datetime, time, timedelta, timezone

import numpy as np
from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models import (
    AIModuleConfig,
    AttendanceRecord,
    Building,
    Camera,
    Event,
    Faculty,
    LessonSession,
    StudentGroup,
    StudentStaff,
)
from app.models.org import OrgUnit
from app.models.presence_visit import PresenceVisit
from app.seed import seed_all
from app.timezone import INSTITUTE_TZ, business_today

random.seed(7)
rng = np.random.default_rng(7)

FIRST_M = ["Aziz", "Bekzod", "Doniyor", "Elyor", "Farrux", "Jasur", "Kamol", "Laziz", "Murod", "Nodir",
           "Otabek", "Rustam", "Sardor", "Temur", "Ulug'bek", "Xurshid", "Sherzod", "Jamshid", "Anvar", "Bobur"]
FIRST_F = ["Dilnoza", "Gulnora", "Madina", "Nilufar", "Sevara", "Shahnoza", "Zarina", "Kamola", "Malika",
           "Nigora", "Feruza", "Mohira", "Lola", "Dildora", "Munisa"]
LAST = ["Aliyev", "Karimov", "Rasulov", "Tursunov", "Yusupov", "Qodirov", "Nazarov", "Ergashev", "Saidov",
        "Mirzayev", "Xolmatov", "Abdullayev", "Sobirov", "Hasanov", "Islomov", "Rahimov", "Umarov", "Jo'rayev"]
FACULTIES = [("Davolash ishi", "DI"), ("Pediatriya", "PD"), ("Stomatologiya", "ST")]
SUBJECTS = ["Anatomiya", "Fiziologiya", "Biokimyo", "Farmakologiya", "Patologiya", "Ichki kasalliklar",
            "Jarrohlik", "Lotin tili", "Gistologiya", "Mikrobiologiya"]
POSITIONS = ["Professor", "Dotsent", "Katta o'qituvchi", "Assistent", "Laborant", "Uslubchi", "Mudir"]


def person_name(female: bool) -> str:
    last = random.choice(LAST)
    if female:
        last = last[:-2] + "ova" if last.endswith("ov") else last + "a"
        return f"{last} {random.choice(FIRST_F)}"
    return f"{last} {random.choice(FIRST_M)}"


def embedding() -> str:
    v = rng.normal(size=512)
    v /= np.linalg.norm(v)
    return json.dumps([round(float(x), 5) for x in v])


def local(day: date, h: int, m: int, s: int = 0) -> datetime:
    return datetime.combine(day, time(h, m, s), tzinfo=INSTITUTE_TZ)


async def main() -> None:
    async with SessionLocal() as db:
        await seed_all(db)
        await db.commit()
        if (await db.execute(select(StudentStaff).limit(1))).scalar_one_or_none() is not None:
            print("Ma'lumot allaqachon bor — o'tkazib yuborildi")
            return

        # Binolar va kameralar
        buildings = {b.name: b for b in (await db.execute(select(Building))).scalars().all()}
        for name in ("Bosh o'quv binosi", "2-o'quv binosi", "Klinika binosi"):
            if name not in buildings:
                b = Building(name=name)
                db.add(b)
                buildings[name] = b
        await db.flush()
        blist = list(buildings.values())[:3]
        now = datetime.now(timezone.utc)
        cameras: list[Camera] = []
        for i in range(12):
            b = blist[i % 3]
            entrance = i < 4
            cam = Camera(
                name=("Kirish " if entrance else "Auditoriya ") + f"{i + 1}",
                ip=f"10.20.0.{i + 10}", port=554, zone="Kirish" if entrance else f"{100 + i}-xona",
                resolution="1080p", status="faol" if i != 11 else "tamirda", building_id=b.id,
                floor=1 if entrance else 1 + i % 3, is_entrance=entrance, is_exit=entrance,
                room_code=None if entrance else f"{100 + i}",
                last_seen_at=now - timedelta(seconds=20) if i not in (9, 10) else now - timedelta(hours=3),
                last_frame_at=now - timedelta(seconds=30) if i not in (8, 9, 10) else None,
            )
            db.add(cam)
            cameras.append(cam)
        await db.flush()

        # Fakultetlar, guruhlar, tuzilma
        faculties = {f.name: f for f in (await db.execute(select(Faculty))).scalars().all()}
        rektorat = OrgUnit(name="Rektorat", kind="rektorat", hemis_id="demo-r")
        db.add(rektorat)
        await db.flush()
        kafedras: list[OrgUnit] = []
        groups: list[tuple[str, Faculty, int]] = []
        for fname, code in FACULTIES:
            fac = faculties.get(fname) or Faculty(name=fname)
            db.add(fac)
            await db.flush()
            faculties[fname] = fac
            dek = OrgUnit(name=f"{fname} fakulteti", kind="fakultet", parent_id=rektorat.id, hemis_id=f"demo-f-{code}")
            db.add(dek)
            await db.flush()
            for k in range(2):
                kaf = OrgUnit(name=f"{SUBJECTS[(len(kafedras)) % len(SUBJECTS)]} kafedrasi", kind="kafedra",
                              parent_id=dek.id, hemis_id=f"demo-k-{code}-{k}")
                db.add(kaf)
                kafedras.append(kaf)
            for course in range(1, 5):
                for g in range(2):
                    gname = f"{code}-{course}{g + 1}{25 - course}"
                    db.add(StudentGroup(name=gname, faculty_id=fac.id, course=course, student_count=20))
                    groups.append((gname, fac, course))
        bolim = OrgUnit(name="Axborot texnologiyalari bo'limi", kind="bolim", parent_id=rektorat.id, hemis_id="demo-b")
        db.add(bolim)
        await db.flush()

        people: list[StudentStaff] = []
        for gname, fac, course in groups:
            for _ in range(20):
                roll = random.random()
                status = "tasdiqlangan" if roll < 0.72 else ("kutilmoqda" if roll < 0.8 else "yoq")
                p = StudentStaff(
                    full_name=person_name(random.random() < 0.5), type="talaba", faculty_id=fac.id,
                    group_or_position=f"{course}-kurs, {gname}", biometrics_status=status,
                    biometric_embedding=embedding() if status != "yoq" else None,
                    biometrics_confirmed_at=now - timedelta(days=40) if status == "tasdiqlangan" else None,
                    self_registered=status == "kutilmoqda",
                    biometrics_review_reason="HEMIS surati bilan mos kelmadi (0.31)" if status == "kutilmoqda" else None,
                )
                db.add(p)
                people.append(p)
        teachers: list[StudentStaff] = []
        for i in range(80):
            unit = kafedras[i % len(kafedras)] if i < 66 else bolim
            status = "tasdiqlangan" if random.random() < 0.85 else "yoq"
            t = StudentStaff(
                full_name=person_name(random.random() < 0.45), type="xodim", org_unit_id=unit.id,
                group_or_position=unit.name, position=random.choice(POSITIONS), biometrics_status=status,
                biometric_embedding=embedding() if status == "tasdiqlangan" else None,
                biometrics_confirmed_at=now - timedelta(days=60) if status == "tasdiqlangan" else None,
            )
            db.add(t)
            people.append(t)
            teachers.append(t)
        await db.flush()

        # Davomat: so'nggi 30 kun (Du–Sha), bugun — qisman
        today = business_today()
        enrolled = [p for p in people if p.biometrics_status == "tasdiqlangan"]
        rows = []
        visits = []
        for back in range(30, -1, -1):
            day = today - timedelta(days=back)
            if day.isoweekday() == 7:
                continue
            for p in enrolled:
                r = random.random()
                if back == 0:
                    # Bugun — hozirgi soatga qarab: ertalab kelganlar
                    if r < 0.55:
                        st, h, m = "keldi", 7, random.randint(30, 59)
                    elif r < 0.62:
                        st, h, m = "kech_keldi", 8, random.randint(15, 59)
                    else:
                        continue
                elif r < 0.84:
                    st, h, m = "keldi", 7, random.randint(25, 59)
                elif r < 0.93:
                    st, h, m = "kech_keldi", random.choice((8, 9)), random.randint(12, 59)
                elif r < 0.99:
                    st, h, m = "kelmadi", None, None
                else:
                    st, h, m = "dam_olish", None, None
                rows.append(AttendanceRecord(
                    student_staff_id=p.id, date=day, status=st,
                    check_in=time(h, m) if h is not None else None,
                    check_out=time(random.randint(15, 18), random.randint(0, 59)) if h is not None and back else None,
                    source="kamera" if h is not None else None,
                ))
                if back == 0 and h is not None:
                    cam = random.choice(cameras[:4])
                    seen = local(day, h, m)
                    visits.append(PresenceVisit(student_staff_id=p.id, camera_id=cam.id, first_seen_at=seen,
                                                last_seen_at=seen + timedelta(minutes=2), sightings=3,
                                                best_similarity=0.62))
        db.add_all(rows)
        db.add_all(visits)

        # Bugungi dars jadvali
        slots = [(8, 30), (10, 10), (11, 50), (14, 0)]
        for idx, (gname, fac, course) in enumerate(groups):
            for s, (h, m) in enumerate(slots[:3]):
                teacher = teachers[(idx * 3 + s) % 66]
                room_cam = cameras[4 + (idx + s) % 7]
                start = local(today, h, m)
                db.add(LessonSession(
                    date=today, group_name=gname, faculty=fac.name, teacher=teacher.full_name,
                    teacher_id=teacher.id, subject=SUBJECTS[(idx + s) % len(SUBJECTS)],
                    camera_id=room_cam.id if (idx + s) % 3 else None,
                    scheduled_start_time=start, scheduled_end_time=start + timedelta(minutes=80),
                    auditorium=room_cam.room_code, building=None,
                ))

        # Hodisalar — so'nggi 14 kun
        modules = (await db.execute(select(AIModuleConfig))).scalars().all()
        for i in range(70):
            mod = random.choice(modules)
            cam = random.choice(cameras)
            occurred = now - timedelta(hours=random.randint(1, 14 * 24))
            st = random.choices(["yangi", "jarayonda", "tasdiqlangan", "rad_etilgan"], [4, 2, 5, 2])[0]
            b = next(x for x in blist if x.id == cam.building_id)
            db.add(Event(
                camera_id=cam.id, camera_name=cam.name, building=b.name, module_code=mod.code,
                module_name=mod.name, group=mod.group or "A", confidence=random.randint(60, 98),
                severity=random.choice(["past", "o'rta", "yuqori"]), status=st, occurred_at=occurred,
                is_trial=False,
            ))
        await db.commit()
        print(f"Tayyor: {len(people)} odam, {len(rows)} davomat yozuvi, {len(cameras)} kamera")


if __name__ == "__main__":
    asyncio.run(main())
