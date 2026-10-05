"""scripts/video_tahlil.py — yozib olingan videolar bilan to'liq ish oqimi:
import -> dars -> tahlil -> hisobot -> holat (haqiqiy modellar bilan)."""

import importlib.util
import json
import shutil
from datetime import datetime, time, timedelta, timezone
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import load_workbook
from sqlalchemy import select

from app.models import AttendanceRecord, Camera, LessonSession, NvrDevice, StudentStaff
from app.timezone import INSTITUTE_TZ, business_today
from tests.conftest import TestSessionLocal
from tests.test_real_models import _make_video, _people, _scene

pytestmark = [
    pytest.mark.daily_mode,
    pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg yo'q"),
]

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "video_tahlil.py"


@pytest.fixture
def cli(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("video_tahlil_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "SessionLocal", TestSessionLocal)
    monkeypatch.setenv("VIDEO_IMPORT_DIR", str(tmp_path / "eksport"))
    return module


def test_time_from_file_names(cli):
    assert cli.stamp_from_name("ch01_20261005085030_20261005093000.mp4") == datetime(2026, 10, 5, 8, 50, 30,
                                                                                       tzinfo=INSTITUTE_TZ)
    assert cli.stamp_from_name("20261005_085030.mp4") == datetime(2026, 10, 5, 8, 50, 30, tzinfo=INSTITUTE_TZ)
    assert cli.stamp_from_name("kirish.mp4") is None
    assert cli.stamp_from_name("20261399_250000.mp4") is None
    assert cli.parse_moment("2026-10-05 08:50") == datetime(2026, 10, 5, 8, 50, tzinfo=INSTITUTE_TZ)
    with pytest.raises(SystemExit):
        cli.parse_moment("05.10.2026")


async def test_full_workflow_with_recorded_video(cli, tmp_path, db_session, seeded, capsys):
    day = business_today() - timedelta(days=1)
    while day.isoweekday() == 7:
        day -= timedelta(days=1)
    people = await _people()
    before = datetime.combine(day - timedelta(days=10), time(9), tzinfo=timezone.utc)
    rows = [
        StudentStaff(full_name=f"Xodim {i}", type="xodim", group_or_position="Kafedra", position="Katta o'qituvchi",
                     biometrics_status="tasdiqlangan", biometric_embedding=json.dumps(e.tolist()),
                     biometrics_confirmed_at=before)
        for i, (e, _b) in enumerate(people)
    ]
    db_session.add_all(rows)
    await db_session.commit()

    # Fayl nomida vaqt yo'q — --boshlanish bilan beriladi.
    video = tmp_path / "kirish-video.mp4"
    _make_video(video, [_scene(people, hidden={3, 4, 5}, coat=None)] * 4 + [_scene(people, hidden=set(), coat=None)] * 4)

    with pytest.raises(SystemExit, match="Kamera topilmadi"):
        await cli.cmd_import(cli_args(fayllar=[str(video)], kamera="Asosiy kirish"))
    await cli.cmd_import(cli_args(fayllar=[str(video)], kamera="Asosiy kirish", yangi=True, tur="kirish",
                                  boshlanish=f"{day} 08:05:00"))
    out = capsys.readouterr().out
    assert "Kamera yaratildi" in out and "kanal 1" in out
    stored = list((tmp_path / "eksport" / "1").iterdir())
    assert [p.name for p in stored] == [f"{day:%Y%m%d}_080500.mp4"]
    assert video.exists()  # nusxa, asl fayl joyida

    async with TestSessionLocal() as db:
        camera = (await db.execute(select(Camera).where(Camera.name == "Asosiy kirish"))).scalars().unique().one()
        nvr = (await db.execute(select(NvrDevice))).scalar_one()
        assert camera.nvr_channel == 1 and camera.nvr_id == nvr.id and nvr.kind == "fayl" and camera.is_entrance

    # Dars (xona kamerasi yaratilib, darsi qo'shiladi).
    await cli.cmd_import(cli_args(fayllar=[str(video)], kamera="201-xona", yangi=True, tur="auditoriya",
                                  boshlanish=f"{day} 09:00:00"))
    await cli.cmd_lesson(cli_args(kamera="201-xona", kun=day.isoformat(), vaqt="09:00-10:20", guruh="DI-101",
                                  oqituvchi="Xodim 2", fan=None, fakultet=None))
    async with TestSessionLocal() as db:
        lesson = (await db.execute(select(LessonSession))).scalars().unique().one()
        assert lesson.teacher == "Xodim 2" and lesson.camera_id is not None

    await cli.cmd_analyze(cli_args(kun=day.isoformat(), oyna=None, majburiy=False))
    out = capsys.readouterr().out
    assert "Holat: tugadi" in out

    async with TestSessionLocal() as db:
        records = {
            r.student_staff_id: r
            for r in (await db.execute(select(AttendanceRecord).where(AttendanceRecord.date == day))).scalars()
        }
    assert {r.id for r in rows} <= set(records)
    assert records[rows[0].id].check_in == time(8, 5, 0)
    assert records[rows[5].id].check_in == time(8, 5, 4)

    target = tmp_path / "natija.xlsx"
    await cli.cmd_report(cli_args(kun=day.isoformat(), chiqish=str(target), tur=None, korsat=3))
    workbook = load_workbook(BytesIO(target.read_bytes()))
    names = [workbook["Natijalar"].cell(row=r, column=1).value for r in range(5, 11)]
    assert names == [f"Xodim {i}" for i in range(6)]
    assert "Xodim 0: keldi" in capsys.readouterr().out

    await cli.cmd_status(cli_args())
    out = capsys.readouterr().out
    assert "Kanal 1: «Asosiy kirish»" in out and "Kanal 2: «201-xona»" in out


async def test_missing_time_is_reported(cli, tmp_path, seeded):
    video = tmp_path / "nomsiz.mp4"
    _make_video(video, [_scene(await _people(), hidden=set(), coat=None)])
    with pytest.raises(SystemExit, match="vaqti aniqlanmadi"):
        await cli.cmd_import(cli_args(fayllar=[str(video)], kamera="Hovli", yangi=True, tur="tashqi"))


def test_camera_matching_order(cli):
    """Yozuv vositasi nomlari: <model>-<IP>_<ID8>.mkv yoki <nom>_<ID8>.mkv."""
    import uuid

    def cam(name, ip, cid):
        return type("Cam", (), {"id": uuid.UUID(cid), "name": name, "ip": ip})()

    a = cam("12-xona", "192.168.0.10", "6a57fd32-0000-0000-0000-000000000001")
    b = cam("23-xona", "192.168.0.31", "38a63911-0000-0000-0000-000000000002")
    c = cam("23-xona", "192.168.0.32", "97435372-0000-0000-0000-000000000003")
    d = cam("O'ng tomon kamera", "192.168.0.16", "f2553f01-0000-0000-0000-000000000004")
    cams = [a, b, c, d]
    # Bir xil nomli ikki kamera — ID qo'shimchasi ajratadi.
    assert cli.match_camera(Path("23-xona_97435372.mkv"), cams) == (c, "ID")
    assert cli.match_camera(Path("IPC-T280HA-LUF-SL-192.168.0.10_ffffffff.mkv"), cams) == (a, "IP")
    assert cli.match_camera(Path("O-ng-tomon-kamera_00000000.mkv"), cams) == (d, "nom")
    assert cli.match_camera(Path("23-xona.mkv"), cams) == (None, "nom bo'yicha 2 ta kamera")
    assert cli.match_camera(Path("Hovli_12345678.mkv"), cams) == (None, "kamera topilmadi")


def test_start_time_from_file_mtime(cli, tmp_path):
    import os

    video = tmp_path / "Asosiy-kirish_8d9a159a.mkv"
    video.write_bytes(b"x")
    ended = datetime(2026, 10, 2, 12, 0, 30, tzinfo=INSTITUTE_TZ)
    os.utime(video, (ended.timestamp(), ended.timestamp()))
    start, source = cli.start_of(video, 3600.0, None)
    assert (start, source) == (datetime(2026, 10, 2, 11, 0, 30, tzinfo=INSTITUTE_TZ), "fayl vaqti")
    named = tmp_path / "20261002_105912.mkv"
    named.write_bytes(b"x")
    assert cli.start_of(named, 60.0, None) == (datetime(2026, 10, 2, 10, 59, 12, tzinfo=INSTITUTE_TZ), "nom")


async def test_folder_import_links_videos_to_cameras(cli, tmp_path, db_session, seeded, capsys):
    import os

    room = Camera(name="12-xona", ip="192.168.0.10", zone="A", resolution="4K", status="faol", room_type="auditoriya")
    door = Camera(name="Asosiy kirish", ip="192.168.0.18", zone="A", resolution="4K", status="faol", is_entrance=True)
    db_session.add_all([room, door])
    await db_session.commit()
    tree = tmp_path / "2026-10-02_10-59-12" / "3-Bino" / "1-qavat"
    (tree / "IP-10").mkdir(parents=True)
    (tree / "IP-18").mkdir(parents=True)
    people = await _people()
    room_video = tree / "IP-10" / f"12-xona_{str(room.id).replace('-', '')[:8]}.mkv"
    door_video = tree / "IP-18" / "IPC-T280HA-LUF-SL-192.168.0.18_00000000.mkv"
    unknown = tree / "IP-18" / "Hovli_12345678.mkv"
    for path in (room_video, door_video, unknown):
        _make_video(path, [_scene(people, hidden=set(), coat=None)] * 2)
    ended = datetime.combine(business_today() - timedelta(days=1), time(12, 0), tzinfo=INSTITUTE_TZ)
    os.utime(door_video, (ended.timestamp(), ended.timestamp()))

    args = cli_args(papka=str(tmp_path / "2026-10-02_10-59-12"), qollash=False, usul="havola", eng_kam=0.0)
    await cli.cmd_folder(args)
    out = capsys.readouterr().out
    assert "«12-xona» (ID" in out and "«Asosiy kirish» (IP" in out and "Hovli_12345678.mkv — kamera topilmadi" in out
    assert "Bu faqat reja" in out and not (tmp_path / "eksport").exists()  # reja hech narsa yozmaydi

    args.qollash = True
    await cli.cmd_folder(args)
    out = capsys.readouterr().out
    assert "2 ta video bog'landi, 1 tasi o'tkazib yuborildi" in out
    async with TestSessionLocal() as db:
        cams = {c.name: c for c in (await db.execute(select(Camera))).scalars().unique()}
    linked = list((tmp_path / "eksport" / str(cams["Asosiy kirish"].nvr_channel)).iterdir())
    assert len(linked) == 1 and linked[0].resolve() == door_video.resolve()  # nusxa emas — havola
    assert linked[0].name.startswith(f"{ended.date():%Y%m%d}_11595")  # 12:00 - davomiylik (bir necha soniya)
    assert room_video.exists() and door_video.exists()


def cli_args(**values):
    defaults = {"boshlanish": None, "yangi": False, "tur": None, "kochirish": False}
    return type("Args", (), {**defaults, **values})()
