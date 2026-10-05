from app.schemas.base import CamelModel


class PublicCameraOut(CamelModel):
    """Deliberately excludes ip/port/rtsp_path/credentials — this endpoint
    has no auth, so only what's safe to hand to an anonymous visitor of the
    public Monitoring page is exposed."""

    id: str
    name: str
    building: str
    zone: str
    department: str = ""
    """Kafedra nomi; biriktirilmagan bo'lsa bo'sh satr."""
    status: str
    stream_url: str | None = None
    floor: int | None = None
    """Qavat raqami; belgilanmagan bo'lsa None (Camera.floor izohiga qarang)."""
    has_video: bool = True
    ptz_enabled: bool = False
    """PTZ boshqaruvi yoqilgan (tugmalar faqat controlPtz huquqi bilan ko'rinadi)."""
    """Kamera tarmoqda javob beryapti, LEKIN tasvir kelyaptimi.

    `status` bilan qo'shilmaydi ataylab: "erishib bo'lmaydi" va
    "erishiladi, lekin tasvir yo'q" — bu ikki xil nosozlik va operator
    uchun bir xil emas. Ikkinchisini oddiy OFLAYN qilib qo'yish
    kamerani devordan yashirar, sababini esa aytmasdi."""


class PublicDepartmentOut(CamelModel):
    name: str
    building: str


class PublicStatsOut(CamelModel):
    total_students: int
    present: int
    absent: int
    late: int
    sleep_incidents: int
    violations: int
    live_cameras: int
    offline_cameras: int
    buildings: list[str]
    departments: list["PublicDepartmentOut"] = []
    """Kafedralar, har biri o'z binosi nomi bilan.

    Bino nomi shu yerda qaytariladi, chunki filtr bosqichma-bosqich
    ishlaydi: bino tanlanganda faqat o'sha binoning kafedralari
    ko'rsatilishi kerak. Aks holda mijoz har bino uchun alohida so'rov
    yuborishi kerak bo'lardi."""


class PublicTopStudentOut(CamelModel):
    id: str
    name: str
    group: str
    attendance_rate: int


class DetectedFaceOut(CamelModel):
    """One face found in a live-detection snapshot — see
    app/routers/public.py's get_live_detection() for how this differs from
    the persistent attendance/sleep pipeline."""

    bbox: list[float]  # [x1, y1, x2, y2], pixel coordinates in the source frame
    person_name: str | None = None
    asleep: bool = False
    # "tanildi" — ro'yxatdagi odam; "notanish" — tahlil qilindi, lekin
    # hech kimga o'xshamadi; "kichik" — yuz juda mayda, tahlil qilinmadi.
    # Ilgari oxirgi ikkisi bir xil ("Noma'lum") chiqardi va operator
    # "tanimadimi yoki ko'rmadimi" degan savolga javob ololmasdi.
    status: str = "kichik"
    # Ro'yxatdagi eng yaqin odamga o'xshashlik (tahlil qilingan yuzlar uchun).
    similarity: float | None = None
    # Izning raqami: bitta odam kadrda yurgan bo'yi o'zgarmaydi — brauzer
    # ramkani ikki natija orasida shu raqam bo'yicha siljitadi.
    track_id: int | None = None


class LiveDetectionFrameOut(CamelModel):
    frame_width: int
    frame_height: int
    faces: list[DetectedFaceOut]
    # Kadr qaysi oqimdan: "asosiy" (4K) yoki "kichik" — mayda yuzlar
    # faqat asosiy oqimda tahlil qilinadi.
    source: str = "kichik"
    # Kadr serverda dekodlangan payt (epoch, soniya). Brauzer ramkani
    # videoning aynan shu paytdagi kadriga qo'yadi (HLS PROGRAM-DATE-TIME).
    captured_at: float | None = None


class LiveDetectionOut(LiveDetectionFrameOut):
    # Oxirgi ~10 s natijalari (eskisidan yangisiga) — ramkalar ular orasida
    # silliq siljitiladi. Bo'sh — eski yo'l (API kadrni o'zi tahlil qildi).
    history: list[LiveDetectionFrameOut] = []
    # Brauzer video soatidan ayiradigan tuzatish (ms) —
    # settings.live_overlay_clock_offset_ms izohiga qarang.
    clock_offset_ms: int = 0
    # Javob berilgan payt (server soati, epoch s). WebRTC videoda vaqt belgisi
    # yo'q — brauzer o'z soati bilan server soati farqini shundan topadi.
    server_time: float | None = None


class CameraAnalysisStatusOut(CamelModel):
    """Oxirgi fon AI sweep natijasi — monitoring modal badge uchun."""

    last_sweep_at: str | None = None
    seconds_ago: int | None = None
    face_count: int = 0
    modules: list[str] = []
    events_raised: int = 0


class CampusFloorOut(CamelModel):
    """Bitta qavat kesimi — Video Monitoring Markazining bino ko'rinishida
    bitta plita. `floor=None` qavati belgilanmagan kameralar guruhi:
    ular yo'qolib qolmasligi uchun alohida chiqariladi."""

    floor: int | None = None
    label: str
    cameras: int = 0
    live: int = 0
    offline: int = 0
    no_video: int = 0
    """Tarmoqda javob beryapti, lekin tasvir kelmayapti (PublicCameraOut.has_video)."""
    events_today: int = 0
    """Bugungi ishchi signallar (sinov namunalari hisobga olinmaydi)."""


class CampusBuildingOut(CamelModel):
    id: str = ""
    """Bo'sh satr — binoga biriktirilmagan kameralar guruhi."""

    name: str
    floors: list[CampusFloorOut] = []
    cameras: int = 0
    live: int = 0
    offline: int = 0
    no_video: int = 0
    events_today: int = 0


class CampusOut(CamelModel):
    """Butun kampus kesimi bitta so'rovda: bino -> qavat -> sanoq.

    Kameralar ro'yxati bu yerda YO'Q ataylab — u faqat operator qavatni
    tanlaganda va faqat o'sha qavat uchun yuklanadi."""

    buildings: list[CampusBuildingOut] = []
    cameras: int = 0
    live: int = 0
    offline: int = 0
    no_video: int = 0
    events_today: int = 0
    generated_at: str = ""
