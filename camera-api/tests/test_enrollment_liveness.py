"""Kamera orqali tiriklik tekshiruvi.

Yuklangan rasm zaif dalil edi: uni boshqa odamning rasmi, telefon
ekranidagi surat yoki qog'ozga bosilgan fotosurat bilan almashtirib
bo'lardi. Endi odam kameraga qarab boshini chapga va o'ngga buradi.

Bu testlar QAROR mantig'ini tekshiradi, o'lchovni emas: yuz aniqlash
soxta ma'lumot bilan almashtiriladi, chunki uch xil burchakdan olingan
haqiqiy fotosuratlar bu yerda mavjud emas va ular bo'lganda ham
tekshiruv modelning aniqligiga bog'lanib qolardi. Burchak o'lchovining
o'zi tests/test_head_pose.py da alohida tekshiriladi.

Eng muhim shart — mijozga ishonilmasligi. Brauzer bosqichlarni o'zi ham
tekshiradi, lekin u faqat foydalanuvchini yo'naltirish uchun: kadrlar
boshqa yo'l bilan ham yuborilishi mumkin, shuning uchun yakuniy hukm
faqat serverda chiqariladi.
"""

import numpy as np
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import settings
from app.models import Faculty, StudentStaff
from app.routers import enrollment
from app.services.face_recognition import DetectedFace
from app.services.sleep_detection import (
    LEFT_EYE_OUTER_INDEX,
    NOSE_TIP_INDEX,
    RIGHT_EYE_OUTER_INDEX,
)

EYE_LEFT_X, EYE_RIGHT_X = 100.0, 200.0
CENTER_X = 150.0
BIG_ENOUGH = settings.enrollment_min_face_height_px + 20


def face(direction: str, *, height: float = BIG_ENOUGH) -> DetectedFace:
    """Berilgan tomonga qaragan soxta yuz."""
    ratio = {"front": 0.0, "left": 0.8, "right": -0.8}[direction]
    lm = np.zeros((68, 3))
    lm[RIGHT_EYE_OUTER_INDEX][0] = EYE_LEFT_X
    lm[LEFT_EYE_OUTER_INDEX][0] = EYE_RIGHT_X
    lm[NOSE_TIP_INDEX][0] = CENTER_X + ratio * (EYE_RIGHT_X - EYE_LEFT_X) / 2
    return DetectedFace(
        embedding=np.ones(512) / np.sqrt(512),
        landmarks_68=lm,
        bbox=np.array([0.0, 0.0, height * 0.8, height]),
    )


def frames(n: int = 3):
    return [("photos", (f"{i}.jpg", b"kadr", "image/jpeg")) for i in range(n)]


@pytest.fixture
def detected(monkeypatch):
    """detect_faces ni boshqariladigan natijaga almashtiradi."""
    state: dict = {"sequence": []}

    async def fake(_frame, *, priority=None):
        if not state["sequence"]:
            return []
        return state["sequence"].pop(0)

    monkeypatch.setattr(enrollment, "detect_faces", fake)
    return state


@pytest.fixture
async def a_record(db_session, seeded) -> StudentStaff:
    faculty = (await db_session.execute(select(Faculty).limit(1))).scalar_one()
    record = StudentStaff(
        full_name="Tiriklik Sinovi", type="xodim", faculty_id=faculty.id,
        group_or_position="Sinov", pinfl="31111111111111",
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    return record


async def submit(client, record, files=None):
    return await client.post(
        f"/api/public/enrollment/{record.id}/submit",
        data={"pinfl": "31111111111111"},
        files=files if files is not None else frames(),
    )


@pytest.mark.usefixtures("seeded")
class TestFrameCount:
    async def test_a_single_frame_is_rejected(self, client: AsyncClient, a_record):
        resp = await submit(client, a_record, frames(1))
        assert resp.status_code == 422
        assert "3 ta kadr" in resp.json()["detail"]

    async def test_two_frames_are_rejected(self, client: AsyncClient, a_record):
        assert (await submit(client, a_record, frames(2))).status_code == 422

    async def test_four_frames_are_rejected(self, client: AsyncClient, a_record):
        """Ortiqcha kadr ham qabul qilinmaydi: har bir kadr aniq bir
        bosqichga tegishli, va ularning tartibi tekshiruvning o'zi."""
        assert (await submit(client, a_record, frames(4))).status_code == 422

    async def test_the_error_names_the_steps(self, client: AsyncClient, a_record):
        """Odam nima qilishi kerakligini bilishi kerak."""
        detail = (await submit(client, a_record, frames(1))).json()["detail"]
        assert "chapga" in detail and "o'ngga" in detail


@pytest.mark.usefixtures("seeded")
class TestPoseVerification:
    async def test_three_correct_turns_pass_the_liveness_check(
        self, client: AsyncClient, a_record, detected, monkeypatch
    ):
        """Tekshiruvdan o'tgach oqim vektor hisoblashga boradi. Bu
        yerda saqlash muhim emas — muhimi, tiriklik shartida
        to'xtatilmagani."""
        detected["sequence"] = [[face("front")], [face("left")], [face("right")]]
        resp = await submit(client, a_record)
        # 422 bo'lsa ham u ENDI tiriklik haqida emas (soxta kadrlardan
        # vektor chiqmaydi) — muhimi, burilish talabi o'tdi.
        assert "talabga mos kelmadi" not in resp.text

    async def test_all_frontal_frames_are_rejected(
        self, client: AsyncClient, a_record, detected
    ):
        """Aynan shu hujum bekor qilinmoqchi bo'lgan narsa: bitta statik
        rasmni uch marta yuborish."""
        detected["sequence"] = [[face("front")], [face("front")], [face("front")]]
        resp = await submit(client, a_record)
        assert resp.status_code == 422
        assert "2-kadr" in resp.json()["detail"]

    async def test_turning_the_wrong_way_is_rejected(
        self, client: AsyncClient, a_record, detected
    ):
        """Chap va o'ng almashib ketsa tekshiruv teskarisiga aylanardi."""
        detected["sequence"] = [[face("front")], [face("right")], [face("left")]]
        resp = await submit(client, a_record)
        assert resp.status_code == 422
        assert "2-kadr" in resp.json()["detail"]

    async def test_the_failing_step_is_named(self, client: AsyncClient, a_record, detected):
        """«Tekshiruvdan o'tmadingiz» degan umumiy xabar odamni nima
        qilishni bilmay qoldirardi va u boshidan qayta-qayta urinaverardi."""
        detected["sequence"] = [[face("front")], [face("left")], [face("front")]]
        detail = (await submit(client, a_record)).json()["detail"]
        assert "3-kadr" in detail
        assert "o'ngga" in detail


@pytest.mark.usefixtures("seeded")
class TestFrameQuality:
    async def test_a_frame_without_a_face_is_rejected(
        self, client: AsyncClient, a_record, detected
    ):
        detected["sequence"] = [[face("front")], [], [face("right")]]
        resp = await submit(client, a_record)
        assert resp.status_code == 422
        assert "yuz aniqlanmadi" in resp.json()["detail"]

    async def test_two_people_in_one_frame_are_rejected(
        self, client: AsyncClient, a_record, detected
    ):
        """Yonida turgan odam kadrga tushsa, qaysi yuz ro'yxatga
        olinayotgani noaniq bo'lib qoladi."""
        detected["sequence"] = [[face("front"), face("front")], [face("left")], [face("right")]]
        resp = await submit(client, a_record)
        assert resp.status_code == 422
        assert "bir nechta yuz" in resp.json()["detail"]

    async def test_a_face_too_far_from_the_camera_is_rejected(
        self, client: AsyncClient, a_record, detected
    ):
        """Kichik yuzda landmark nuqtalari orasidagi farq shovqindan
        ajralmaydi — burilish burchagi o'lchov bo'lmay qoladi."""
        small = settings.enrollment_min_face_height_px - 10
        detected["sequence"] = [[face("front", height=small)], [face("left")], [face("right")]]
        resp = await submit(client, a_record)
        assert resp.status_code == 422
        assert "yaqinroq keling" in resp.json()["detail"]


@pytest.mark.usefixtures("seeded")
class TestPoseCheckEndpoint:
    async def test_it_confirms_a_matching_pose(self, client: AsyncClient, detected):
        detected["sequence"] = [[face("left")]]
        resp = await client.post(
            "/api/public/enrollment/pose-check",
            data={"expected": "left"},
            files={"photo": ("probe.jpg", b"kadr", "image/jpeg")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["direction"] == "left"
        assert body["faceFound"] is True

    async def test_it_rejects_a_mismatching_pose_and_says_what_to_do(
        self, client: AsyncClient, detected
    ):
        detected["sequence"] = [[face("front")]]
        resp = await client.post(
            "/api/public/enrollment/pose-check",
            data={"expected": "right"},
            files={"photo": ("probe.jpg", b"kadr", "image/jpeg")},
        )
        body = resp.json()
        assert body["ok"] is False
        assert body["hint"]

    async def test_no_face_is_reported_without_an_error(self, client: AsyncClient, detected):
        """Bu endpoint sekundiga bir-ikki marta chaqiriladi. Yuz
        ko'rinmagani xato emas — odam hali joylashib olmagan."""
        detected["sequence"] = [[]]
        resp = await client.post(
            "/api/public/enrollment/pose-check",
            data={"expected": "front"},
            files={"photo": ("probe.jpg", b"kadr", "image/jpeg")},
        )
        assert resp.status_code == 200
        assert resp.json()["faceFound"] is False
        assert "ko'rinmayapti" in resp.json()["hint"]

    async def test_an_unknown_step_is_rejected(self, client: AsyncClient):
        resp = await client.post(
            "/api/public/enrollment/pose-check",
            data={"expected": "yuqoriga"},
            files={"photo": ("probe.jpg", b"kadr", "image/jpeg")},
        )
        assert resp.status_code == 422

    async def test_it_reports_the_turn_ratio_for_guidance(self, client: AsyncClient, detected):
        detected["sequence"] = [[face("right")]]
        resp = await client.post(
            "/api/public/enrollment/pose-check",
            data={"expected": "right"},
            files={"photo": ("probe.jpg", b"kadr", "image/jpeg")},
        )
        assert resp.json()["ratio"] < 0  # o'ngga burilgan — manfiy


@pytest.mark.usefixtures("seeded")
class TestBrokenFramesDoNotCrash:
    """Jonli yo'naltirish sekundiga bir marta chaqiriladi.

    Brauzer video hali tayyor bo'lmaganda nol baytli kadr yuborishi
    mumkin, va bunday kadr server xatosini bermasligi kerak: bu
    jurnalni to'ldirar va odam sababini bilmasdan qolardi.

    Serverda haqiqatan shunday bo'lgan: bo'sh bufer uchun OpenCV None
    qaytarmaydi, balki xato TASHLAYDI, va u tutilmagan edi.
    """

    @pytest.mark.parametrize(
        "payload",
        [pytest.param(b"", id="bo'sh"),
         pytest.param(b"not an image", id="axlat"),
         pytest.param(b"\xff\xd8", id="yarim-jpeg")],
    )
    async def test_pose_check_answers_instead_of_failing(self, client: AsyncClient, payload):
        resp = await client.post(
            "/api/public/enrollment/pose-check",
            data={"expected": "front"},
            files={"photo": ("probe.jpg", payload, "image/jpeg")},
        )
        assert resp.status_code == 200
        assert resp.json()["faceFound"] is False

    async def test_submit_reports_which_frame_could_not_be_read(
        self, client: AsyncClient, a_record
    ):
        """Yakuniy yuborishda esa jim o'tib ketish mumkin emas — odam
        qaysi kadr o'qilmaganini bilishi kerak."""
        resp = await client.post(
            f"/api/public/enrollment/{a_record.id}/submit",
            data={"pinfl": "31111111111111"},
            files=[("photos", (f"{i}.jpg", b"", "image/jpeg")) for i in range(3)],
        )
        assert resp.status_code == 422
        assert "1-kadr" in resp.json()["detail"]
