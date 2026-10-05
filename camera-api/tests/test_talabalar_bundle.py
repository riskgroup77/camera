"""Shifrlangan talabalar to'plami.

Repozitoriy ochiq, shuning uchun bu testlarning asosiy vazifasi ikkita:
ro'yxat faylda OCHIQ holda qolmasligi va noto'g'ri kalit bilan bazaga
hech narsa yozilmasligi. Qolgani — import qoidalari —
tests/test_import_talabalar.py da.
"""

import importlib.util
import json

import pytest
from sqlalchemy import func, select

from app.models import StudentStaff
from scripts.import_talabalar import (
    KEY_ENV,
    WrongPassphraseError,
    pack,
    run_bundle,
    seal,
    unseal,
)
from tests.conftest import TestSessionLocal

KEY = "QK7M-X4TP-9WDR-H3VN"


def _row(pinfl, name, file_course, group="DI-1625"):
    return {"pinfl": pinfl, "name": name, "passport": "AA1000001", "group": group,
            "faculty": "", "file_course": file_course, "source": "t.xlsx / 1"}


ROWS = [
    _row("60000000000011", "NAZAROVA DILNOZA OYBEK QIZI", 1),
    _row("50000000000022", "RAHIMOV JASUR BAHODIR O‘G‘LI", 1),
    _row("60000000000033", "TO‘XTAYEVA MALIKA SHERZOD QIZI", 4, group="TPI-1022"),
]


class TestEncryption:
    def test_round_trip(self):
        assert unseal(seal({"rows": ROWS}, KEY), KEY) == {"rows": ROWS}

    def test_typing_differences_in_the_key_are_forgiven(self):
        blob = seal({"rows": ROWS}, KEY)
        assert unseal(blob, "qk7m x4tp 9wdr h3vn")["rows"] == ROWS

    def test_wrong_key_is_rejected(self):
        blob = seal({"rows": ROWS}, KEY)
        with pytest.raises(WrongPassphraseError):
            unseal(blob, "AAAA-BBBB-CCCC-DDDD")

    def test_tampered_data_is_rejected(self):
        """GCM butunlikni ham tekshiradi: buzilgan matn "qisman to'g'ri"
        ro'yxat bo'lib ochilmaydi."""
        blob = seal({"rows": ROWS}, KEY)
        middle = len(blob) // 2
        tampered = blob[:middle] + ("A" if blob[middle] != "A" else "B") + blob[middle + 1:]
        with pytest.raises((WrongPassphraseError, ValueError)):
            unseal(tampered, KEY)

    def test_an_empty_key_is_rejected(self):
        with pytest.raises(WrongPassphraseError):
            seal({"rows": ROWS}, "   ")


class TestPackedFile:
    @pytest.fixture
    def packed(self, tmp_path):
        source = tmp_path / "talabalar.json"
        source.write_text(json.dumps({"generated_at": "2026-09-14T15:00:00", "rows": ROWS}, ensure_ascii=False),
                          encoding="utf-8")
        out = tmp_path / "talabalar_malumot.py"
        courses = pack(source, out, KEY)
        return out, courses

    def test_no_personal_data_is_readable_in_the_file(self, packed):
        out, _ = packed
        text = out.read_text(encoding="utf-8")
        for row in ROWS:
            assert row["pinfl"] not in text
            assert row["name"].split()[0] not in text
        assert "AA1000001" not in text
        assert KEY not in text and KEY.replace("-", "") not in text

    def test_course_counts_are_shifted_and_visible(self, packed):
        out, courses = packed
        assert courses == {2: 2, 5: 1}
        spec = importlib.util.spec_from_file_location("talabalar_malumot", out)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module.KURSLAR == {2: 2, 5: 1}
        assert unseal(module.MALUMOT, KEY)["rows"] == ROWS


@pytest.mark.usefixtures("seeded")
class TestRunningTheBundle:
    async def _students(self, db_session) -> int:
        return await db_session.scalar(
            select(func.count()).select_from(StudentStaff).where(StudentStaff.type == "talaba"))

    async def _run(self, argv, key, monkeypatch):
        monkeypatch.setenv(KEY_ENV, key)
        blob = seal({"rows": ROWS}, KEY)
        return await run_bundle(blob, {2: 2, 5: 1}, argv=argv, session_factory=TestSessionLocal)

    async def test_wrong_key_writes_nothing(self, db_session, monkeypatch):
        assert await self._run([], "NOTO-GRIK-ALIT-0000", monkeypatch) == 2
        assert await self._students(db_session) == 0

    async def test_dry_run_writes_nothing(self, db_session, monkeypatch):
        assert await self._run(["--dry-run"], KEY, monkeypatch) == 0
        assert await self._students(db_session) == 0

    async def test_import_all(self, db_session, monkeypatch):
        assert await self._run([], KEY, monkeypatch) == 0
        assert await self._students(db_session) == 3

    async def test_one_course_only(self, db_session, monkeypatch):
        assert await self._run(["--kurs", "5"], KEY, monkeypatch) == 0
        names = (await db_session.execute(
            select(StudentStaff.full_name).where(StudentStaff.type == "talaba"))).scalars().all()
        assert names == ["To'xtayeva Malika Sherzod qizi"]
