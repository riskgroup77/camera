from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    port: int = 8080
    database_url: str
    # SQLAlchemy's own defaults (pool_size=5, max_overflow=10 -> 15 total)
    # were sized for a handful of concurrent requests, not 14 background AI
    # sweep loops each opening their own per-camera sessions on top of
    # normal admin-panel traffic. Raise these in .env for a production
    # server with many cameras; the defaults here are already well above
    # SQLAlchemy's own for a dev/small deployment.
    db_pool_size: int = 20
    db_max_overflow: int = 40
    db_pool_timeout_seconds: int = 30
    jwt_secret: str
    jwt_ttl_hours: int = 12
    cors_origin: str = "http://localhost:5173"
    encryption_key: str

    s3_endpoint_url: str = "http://127.0.0.1:9000"
    # Used only to generate presigned GET URLs (app/storage.py presigned_url()).
    # In Docker Compose, s3_endpoint_url is the internal service name
    # ("http://minio:9000") that the api container uses to reach MinIO for
    # actual uploads — but that hostname means nothing to the browser the
    # presigned URL gets handed to, so presigning needs the host-reachable
    # address instead. Defaults to s3_endpoint_url for local (non-container)
    # dev, where the two are the same address.
    s3_public_endpoint_url: str | None = None
    s3_access_key: str = "camera_minio_admin"
    s3_secret_key: str = "camera_minio_dev_pw"
    s3_bucket: str = "camera-uploads"
    s3_region: str = "us-east-1"

    mediamtx_api_url: str = "http://127.0.0.1:9997"
    mediamtx_hls_base_url: str = "http://127.0.0.1:8888"
    # Browser-facing HLS base (mediamtx_hls_base_url) often differs from what
    # the API container can reach (e.g. https://stream.cam.fermi.uz vs
    # http://mediamtx:8888 inside Docker). AI/frame_grabber uses this internal
    # base to rewrite public stream URLs before ffmpeg opens them.
    mediamtx_hls_internal_base_url: str | None = None

    # Parolni tiklash havolasi shu manzil ostida quriladi (frontend'ning
    # ResetPasswordPage marshruti). SMTP sozlanmagan bo'lsa (dev holati),
    # email yuborilmaydi — havola shunchaki strukturaviy logga yoziladi.
    # Background cleanup job (app/jobs/cleanup.py) — how far back AuditLog
    # rows are kept, and how often the sweep runs. No Celery/cron here: a
    # plain asyncio loop started from main.py's lifespan is enough for a
    # single periodic sweep.
    audit_log_retention_days: int = 90
    # AI-detected incidents (app/models/event.py) — older rows are purged
    # by app/jobs/cleanup.py on the same schedule as audit logs.
    event_retention_days: int = 180
    cleanup_interval_hours: int = 24

    # Camera reachability sweep (app/jobs/camera_health.py) — how often every
    # camera marked "faol" gets a lightweight TCP reachability check, and how
    # long a successful check stays "fresh" before a camera reads as offline
    # again. Freshness should be a few multiples of the interval so one
    # missed/slow sweep tick doesn't immediately flip a healthy camera to
    # "offline".
    camera_health_interval_seconds: int = 30
    camera_health_freshness_seconds: int = 90
    # Parallel TCP checks during camera_health sweep (300 cameras @ 48 ≈ 19 waves × 3s)
    camera_health_concurrency: int = 32
    # How long a faol camera must stay unreachable before raising an admin
    # alert (AuditLog entry + structured WARNING log).
    # 0 = alert on the first failed health check; negative (e.g. -1) disables alerts.
    camera_offline_alert_minutes: int = 5

    # Parallel MediaMTX registrations on API startup (stream_sync.py).
    stream_sync_concurrency: int = 24

    # Automatic attendance via face recognition (app/jobs/attendance_ai.py,
    # app/services/frame_grabber.py) — TT kriteriya 6/7/8, no external AI
    # API: everything runs locally through the same InsightFace model
    # app/services/face_recognition.py already uses for enrollment/compare.
    attendance_ai_interval_seconds: int = 30
    # 1:N identification against the whole enrolled population is a
    # higher false-accept risk than the 1:1 verification used at enrollment
    # time (face_recognition.MATCH_THRESHOLD=0.45) — deliberately stricter.
    # 2026-09-16 kalibrlash: productionda 607 ta ro'yxatdan o'tgan
    # xodimdan bir kunda atigi 4 tasi tanilardi. Kirish kameralaridagi
    # o'xshashlik taqsimoti haqiqiy mosliklar 0.45-0.57 oralig'ida
    # to'planishini ko'rsatdi — ya'ni 0.55 chegara ro'yxatdagi odamning
    # o'zini ham "tanimasdi". Sabab: xodimlar bazasidagi rasm hujjat
    # rasmi, kamera kadri esa boshqa sharoit (yorug'lik, burchak,
    # masofa) — ArcFace uchun bu tabiiy ravishda past o'xshashlik.
    # Chegara pasaytirildi, xavfi esa attendance_ai_strict_margin bilan
    # qoplandi.
    attendance_ai_match_threshold: float = 0.50
    # Qat'iy moslik uchun "ajralish": eng yaqin nomzod ikkinchisidan
    # shuncha uzoq bo'lishi kerak. Ikki odam bir xil darajada o'xshash
    # chiqsa moslik qabul qilinmaydi (app/services/face_matching.py).
    attendance_ai_strict_margin: float = 0.05
    # "Yumshoq" moslik (app/services/face_matching.py graded_matches).
    # CCTV kadridagi kichik/qiya yuz ro'yxatdagi odamning o'zi bo'lsa ham
    # ko'pincha 0.45-0.55 oralig'ida qoladi va qat'iy chegara uni hech
    # qachon tanimaydi. Shu oraliqda moslik faqat ikki shart bilan qabul
    # qilinadi: eng yaqin nomzod ikkinchisidan kamida margin qadar uzoq VA
    # xuddi shu odam confirm_window ichida yana bir kadrda mos kelgan
    # (app/services/recognition_stats.py). 0 yoki >= match_threshold
    # qiymati yumshoq moslikni butunlay o'chiradi.
    attendance_ai_relaxed_threshold: float = 0.42
    attendance_ai_relaxed_margin: float = 0.08
    attendance_relaxed_confirm_window_seconds: int = 180
    attendance_relaxed_min_gap_seconds: float = 0.5
    # O'sha kameraning o'zi yumshoq moslikni faqat shuncha soniyadan keyin
    # tasdiqlay oladi (ketma-ket kadrlar mustaqil dalil emas); boshqa kamera —
    # min_gap bilan (recognition_stats.confirm_relaxed).
    attendance_relaxed_same_camera_gap_seconds: float = 10.0
    # Bundan kichik (piksel balandligi) yuz uchun faqat qat'iy moslik:
    # juda kichik yuzning vektori ishonchsiz.
    attendance_min_face_px: int = 40
    # Kichik yuz uchun qat'iy chegara ham YUQORI qoladi. 2026-09-16 da
    # umumiy chegara 0.55 -> 0.50 ga tushirildi, chunki kirish
    # kamerasidagi KATTA yuzlar (60-80 px) shu oraliqda qolib ketardi.
    # Ammo 10-20 pikselli yuzning vektori shovqinga to'la — unga
    # yumshatilgan chegarani qo'llash boshqa odamga davomat yozish
    # xavfini ochadi, shuning uchun ular eski chegarada qoladi.
    attendance_small_face_match_threshold: float = 0.55
    # Shundan past (piksel balandligi) yuz umuman tahlil qilinmaydi:
    # embedding ham, 3D landmark ham hisoblanmaydi, faqat bbox qoladi
    # (tashxisda "kichik yuz" bo'lib sanaladi). 2026-09-18 da o'lchandi:
    # o'rtacha yuzi 8-15 px bo'lgan xona kameralarida bir kun davomida eng
    # yaxshi o'xshashlik ~0.31 dan (moslik chegarasi 0.50) oshmagan, lekin
    # har bir yuz to'liq R50 chaqiruvini olardi —
    # app/services/face_recognition.py _detect_faces_sync izohiga qarang.
    face_analysis_min_px: int = 20
    # Doimiy kuzatuvchi (davomat) uchun alohida, yuqoriroq chegara. 20-32 px
    # yuzning ArcFace vektori deyarli tasodifiy: 2026-09-20 o'lchovida median
    # 22 px lik 8884 yuzdan birortasi ham mos kelmagan, har biri esa ~0.42 s
    # R50 chaqiruvini olardi. Bunday yuzlarni 4K zoom (face_zoom_max_px=45)
    # baribir asosiy oqimdan qayta ko'radi.
    attendance_watch_min_face_px: int = 32
    # Aniq notanish yuz (sifatli, eng yaqin o'xshashlik yumshoq chegaradan
    # unknown_track_margin pastda) har kadrda qayta tahlil qilinmaydi —
    # kadrdan kadrga kuzatiladi va shuncha soniyada bir qayta tekshiriladi.
    # Bazada yuzi yo'q odamlar (2026-09-24: 73%) kamerada turgan bo'yi har
    # kadrda ArcFace olardi.
    unknown_recheck_seconds: float = 2.5
    unknown_track_margin: float = 0.05
    # ── Kichik yuzni asosiy oqimdan yaqinlashtirib tanish ───────────────
    # (app/services/face_zoom.py). 2026-09-20 o'lchovi: bir kunda 112433
    # kadr, 8884 yuz, ulardan 8079 tasi tanish chegarasidan kichik, yuz
    # balandligi medianasi 22 px, tanish 0 ta — odamlar 720p substreamda
    # shunchaki juda kichik. Asosiy oqim 4K, ya'ni o'sha yuz ~3 barobar
    # katta. Doimiy 4K o'qish mumkin emas (AVX'siz CPU, tarmoq), lekin
    # kichik yuz KO'RINGANDA bitta 4K kadr olib, faqat o'sha yuzlar
    # atrofini qayta tahlil qilish mumkin.
    face_zoom_enabled: bool = True
    # Shu balandlikdan (piksel) kichik yuz zoom uchun ham nomzod emas:
    # 10 px dan kichik ramka ko'pincha yuz emas (dog', stul suyanchig'i),
    # asosiy oqimda ham u 30 px atrofida qoladi. Yuqori chegara —
    # face_analysis_min_px (undan kattasi allaqachon tahlil qilingan).
    face_zoom_min_px: int = 10
    # Yuqori chegara: shundan kichik yuzlar yaqinlashtiriladi. Bu
    # face_analysis_min_px dan KATTA: 20-40 px lik yuz tahlil qilinadi,
    # lekin 2026-09-20 o'lchovida ular hech qachon mos kelmadi (median 22 px,
    # 8884 yuzdan 0 ta moslik) — ular ham 4K dan qayta ko'riladi.
    face_zoom_max_px: int = 45
    # Bitta kadrda shundan ko'p hudud qayta tahlil qilinmaydi: har biri
    # 4K kadrda alohida detektor chaqiruvi (AVX'siz CPU'da ~0.3-0.5 s).
    face_zoom_max_faces: int = 4
    # Yuz ramkasi hudud (ROI) ga aylanishdan oldin shuncha barobar
    # kengaytiriladi — odam ikki kadr orasida siljigan bo'ladi va
    # detektorga yuz atrofidagi kontekst kerak.
    face_zoom_margin: float = 2.5
    # Bitta kamera asosiy oqimdan kadrni shundan tez-tez olmaydi.
    face_zoom_interval_seconds: int = 15
    # Bir vaqtning o'zida shuncha kameragina 4K kadr oladi — tarmoq va
    # CPU yuklamasining asosiy chegarasi shu.
    face_zoom_max_concurrent_cameras: int = 6
    # Asosiy oqimdan kadr kutish. Kalit kadr 4-8 s da bir keladi; shundan
    # keyin o'quvchi (ffmpeg) DARHOL yopiladi, ya'ni 4K ulanish faqat shu
    # necha soniya yashaydi.
    face_zoom_wait_seconds: float = 8.0
    # ── Devordagi rasm ("statik yuz") ni o'tkazib yuborish ──────────────
    # (app/services/static_faces.py). 2026-09-20, yakshanba, bino bo'sh:
    # 1555 ta "yuz", 290 ta 4K zoom urinishi, 0 ta moslik — kesimlarda
    # ma'lumot stendidagi xodimlar surati va anatomiya plakati. Bunday yuz
    # har tekshiruvda qaytadan topiladi va har safar eng qimmat yo'lga
    # (zoom pass) tushadi.
    static_face_skip_enabled: bool = True
    # Eslab qolingan ramka bilan shundan yuqori ustma-ust tushish "aynan
    # o'sha joy" hisoblanadi. 0.9 — juda qat'iy (kuzatuv uchun 0.4 yetadi):
    # tirik odam bir necha kadr davomida piksel aniqligida turmaydi, rasm esa
    # umuman qimirlamaydi.
    static_face_iou: float = 0.9
    # Statik deb belgilash uchun: shuncha ALOHIDA ko'rinish VA shuncha
    # vaqt oralig'i — ikkalasi ham. 90 daqiqa ataylab tanlandi: eng uzun
    # dars bloki (juft dars) 80 daqiqa, ya'ni butun dars davomida stulda
    # qimirlamay o'tirgan odam ham chegaraga yetmaydi; plakat esa bir necha
    # soatda ham, ertasiga ham o'sha joyda turaveradi.
    static_face_min_hits: int = 40
    static_face_min_span_seconds: int = 5400
    # Ikki sanoq orasidagi eng kichik oraliq: sekundiga bir kadr o'qiydigan
    # kirish kuzatuvchisi sanoqni daqiqalarda to'ldirib yubormasin.
    static_face_min_gap_seconds: int = 20
    # Shuncha vaqt ko'rinmagan ramka unutiladi (stend olib tashlandi,
    # kamera burildi) — keyin u odatdagidek qayta tekshiriladi.
    static_face_expire_seconds: int = 10800
    # O'sha joyda bir marta HAQIQIY odam tanilgan bo'lsa, ramka shuncha vaqt
    # statik bo'la olmaydi. Eng xavfli xato — tirik odamni rasm deb
    # belgilash, shuning uchun bu chegara ataylab uzun (ish kuni).
    static_face_person_memory_seconds: int = 21600
    # Xotira chegarasi: bitta kamerada shuncha ramka (nomzod + statik) va
    # jami shuncha kamera eslanadi.
    static_face_max_boxes_per_camera: int = 32
    static_face_max_cameras: int = 400
    # Detektor kadrni o'z nisbatida tahlil qiladi (app/services/face_recognition.py
    # detection_input_size). 2026-09-19 o'lchovi: 107 kameraning 99 tasi AI
    # uchun 640x360 substreamdan o'qiladi — ular uchun 640x384 kirish eski
    # 640x640 dan ~40% arzon. Asosiy oqim (1920-2560 px) esa 1280 gacha
    # tahlil qilinadi: 640 ga siqilganda 40 px lik yuz 10-13 px bo'lib
    # detektordan tushib qolardi. False — eski 640x640.
    # O'lchov (ai-worker, AVX'siz QEMU CPU, 2 oqim): 640x640 — 705 ms,
    # 640x384 — 421 ms, 1280x736 — 1652 ms. 960 — murosa (~1 s): 1080p
    # kadrdagi 40 px yuz detektorda ~20 px (SCRFD ~10 px dan topadi),
    # embedding esa baribir TO'LIQ o'lchamli kadrdan olinadi.
    face_det_native_resolution: bool = True
    # QR orqali o'zini ro'yxatdan o'tkazganlar avtomatik tasdiqlanadi
    # (app/services/self_enrollment.py). Yuzi boshqa tasdiqlangan odamga
    # shu o'xshashlikdan yuqori bo'lsa — tekshiruvga ("kutilmoqda") qoladi.
    self_enrollment_auto_approve: bool = True
    self_enrollment_duplicate_threshold: float = 0.55
    # Shaxsni tasdiqlash (app/services/identity_check.py): topshirilgan yuz
    # HEMIS'dagi surat bilan 1:1 solishtiriladi. Mos kelsa — avtomatik
    # tasdiq; mos kelmasa yoki surat bo'lmasa — administrator ko'radi.
    # O'lchov (2026-09-26, prod, 3 tomonlama ro'yxatdan o'tgan va HEMIS surati
    # bor odamlar): o'zi bilan 0.51-0.78, boshqa odam bilan <= 0.28.
    # Super Admin va Admin uchun ikki bosqichli kirishni (TOTP) majburiy qilish:
    # yoqilsa, 2FA'siz administrator faqat uni sozlash sahifasiga kira oladi
    # (app/dependencies.py).
    # O'chirilgan (2026-09-27, foydalanuvchi so'rovi): 2FA ixtiyoriy — har kim
    # o'z profilida yoqishi mumkin. Majburiy qilish: ADMIN_2FA_REQUIRED=true.
    admin_2fa_required: bool = False
    self_enrollment_identity_check: bool = True
    self_enrollment_identity_threshold: float = 0.40
    face_det_max_side: int = 1280  # 720p qo'shimcha oqim to'liq o'lchamda tahlil qilinadi
    face_det_min_side: int = 640
    # Yuz sifati darvozasi (face_recognition.face_quality_ok): faqat YUMSHOQ
    # moslik va avtomatik galereya uchun. Qat'iy moslik bunga bog'liq emas.
    face_quality_gate_enabled: bool = True
    face_quality_min_det_score: float = 0.60
    # |burun siljishi| / ko'zlar oralig'i; ~0.35 — taxminan 35-40 daraja burilish.
    face_quality_max_yaw: float = 0.35
    # Hizalangan 112x112 kesimning Laplas dispersiyasi; shundan past — xira.
    face_quality_min_sharpness: float = 25.0
    # Kamera-domen galereyasi (app/services/face_gallery.py). Productionda
    # ro'yxatdagi rasm — hujjat rasmi, kamera kadri esa boshqa yorug'lik va
    # burchak: tanilgan tashriflarning 82% i o'xshashlik 0.45-0.60 da
    # (2026-09-19). Ishonchli (yuqori o'xshashlik, katta, sifatli) tanilgan
    # yuzning vektori odamning qo'shimcha namunasi sifatida saqlanadi va
    # keyingi safar odam "asl rasm YOKI kamera namunalari"dan eng yaqiniga
    # solishtiriladi — o'sha kamera sharoitida o'xshashlik sezilarli oshadi.
    # Namuna faqat ASL rasm bilan o'xshashlik gallery_min_similarity dan
    # yuqori bo'lganda qo'shiladi (galereya namunasi orqali emas) — boshqa
    # odamning yuzi galereyaga "sirg'alib" kirib qolmasligi uchun.
    face_gallery_enabled: bool = True
    face_gallery_auto_add: bool = True
    face_gallery_min_similarity: float = 0.58
    face_gallery_min_margin: float = 0.10
    face_gallery_min_face_px: int = 56
    face_gallery_max_per_person: int = 5
    # Mavjud namunaga shundan yaqin bo'lsa yangisi qo'shilmaydi (takror).
    face_gallery_dedupe_similarity: float = 0.90
    # Bitta odamga ikki namuna orasidagi eng qisqa vaqt.
    face_gallery_min_interval_seconds: int = 600
    # Galereya namunasi orqali topilgan moslik uchun qo'shimcha talab:
    # asl rasm bilan o'xshashlik ham kamida shuncha bo'lsin.
    face_gallery_anchor_floor: float = 0.30
    # Kadrlar bo'yicha yuz izini birlashtirish (app/services/face_tracks.py).
    # Auditoriyada o'tirgan odam bir joyda qoladi: shu joydagi yuzning
    # bir necha kadrdagi vektorlari o'rtachalanadi — shovqin kamayadi va
    # o'xshashlik ko'tariladi. Tanilmagan yuzlar uchungina ishlaydi.
    face_track_fusion_enabled: bool = True
    face_track_iou: float = 0.30
    face_track_max_age_seconds: float = 180.0
    # Izga qo'shilayotgan yangi vektor iz o'rtachasiga shundan kam o'xshash
    # bo'lsa — bu boshqa odam, iz yangidan boshlanadi.
    face_track_min_self_similarity: float = 0.35
    face_track_max_frames: int = 8
    # Birlashtirilgan iz kamida shuncha kadrdan iborat bo'lsa ishlatiladi.
    face_track_min_frames: int = 2
    # Asosiy oqimga tanlab o'tkazish (app/services/stream_promotion.py). Tarmoq
    # hamma xona kamerasining 4K oqimini ko'tarmaydi (ai_room_cameras_main_stream
    # =False), lekin yuz ko'rinadigan-u, kichikligi sababli tanilmaydigan bir
    # nechta kamerani asosiy oqimga o'tkazish mumkin. Byudjet — bir vaqtda
    # asosiy oqimda ishlaydigan xona kameralari soni.
    # 2026-09-19: qo'shimcha oqim 1280x720 ga ko'tarildi, yuz aniqlash esa
    # kadrni baribir 1280 gacha kichraytiradi — 4K asosiy oqim endi yuzni
    # kattalashtirmaydi, faqat tarmoq/CPU yuklaydi va tez-tez kadr bermaydi.
    ai_main_stream_promotion_enabled: bool = False
    # Perimetr kameralari ham shu sababdan substream'da (kirish kamerasi — ai_entrance_use_main_stream).
    ai_perimeter_main_stream: bool = False
    ai_main_stream_promotion_budget: int = 3
    # Kamerada bugun kamida shuncha yuz ko'ringan bo'lsin...
    ai_main_stream_promotion_min_faces: int = 10
    # ...va ularning o'rtacha balandligi shu oraliqda bo'lsin: pastroq —
    # asosiy oqimda ham tanib bo'lmaydi; yuqoriroq — substream yetarli.
    ai_main_stream_promotion_min_px: int = 10
    ai_main_stream_promotion_max_px: int = 40
    # Tanlangan kamera kamida shuncha vaqt asosiy oqimda qoladi.
    ai_main_stream_promotion_hold_seconds: int = 1800
    ai_main_stream_promotion_refresh_seconds: int = 120
    # Yuzi hech qachon tanib bo'lmaydigan kameralar (keng qamrovli
    # auditoriya/koridor kameralari) yuz sweepidan chiqariladi.
    #
    # Productionda o'lchandi (2026-09-16): 107 kameraning taxminan
    # yarmida yuz balandligi 8-20 piksel, ya'ni attendance_min_face_px
    # (40) dan ancha past. Bunday kadr InsightFace uchun shovqin: hech
    # kim tanilmaydi, lekin har aylanishda kadr olinadi va model
    # chaqiriladi — unified_face sweepining bitta aylanishi 129 soniyaga
    # cho'zilishining asosiy sababi shu.
    #
    # Qaror kamera bo'yicha, o'sha kunning o'z statistikasidan chiqadi va
    # abadiy emas: har face_blind_recheck_every aylanishda kamera qayta
    # tekshiriladi (kamera burilishi, yaqinlashtirilishi yoki oqim
    # sifatini o'zgartirishi mumkin), statistika esa har kuni noldan
    # boshlanadi.
    face_blind_skip_enabled: bool = True
    face_blind_min_faces: int = 40
    face_blind_small_ratio: float = 0.95
    face_blind_recheck_every: int = 20
    # "HH:MM" — kunlik davomatda kech qolish chegarasi (mahalliy vaqt).
    # Kunlik davomat dars jadvaliga BOG'LIQ EMAS: odamning birinchi
    # ko'rinishi shu vaqtdan keyin bo'lsa — "kech_keldi". Darsga
    # bog'liqlik alohida ko'rsatiladi (app/routers/presence.py).
    attendance_ai_late_cutoff: str = "09:00"
    # "HH:MM" — shundan keyingi birinchi KIRISH ko'rinishi ham "keldi", vaqti
    # noma'lum. Kirish kameralari bir vaqtda chiqish kamerasi: kunning
    # birinchi ko'rinishi 16:30 da bo'lsa, bu ko'pincha ketayotgan odam
    # (ertalab kamera uni o'tkazib yuborgan). 2026-09-18 da tuzatishdan
    # keyin 16:00 dan so'ng yana 5 ta shunday "kech keldi" yozildi.
    # Bo'sh qator — cheklov yo'q (eski xatti-harakat).
    attendance_late_window_end: str = "12:00"
    # Soddalashtirilgan davomat (2026-09-19 qarori): odam kunda birinchi
    # marta istalgan kameraga tushganda "keldi" va o'sha soat yoziladi.
    # "Kech keldi" ham, ketish vaqti (check_out) ham yozilmaydi.
    attendance_arrival_only: bool = False
    # Kunlik davomat BARCHA kameralarda (faqat kirish eshigida emas): har
    # faol kamera doimiy kuzatuvchi oladi va asosiy (yuqori sifatli) oqim
    # o'qiladi — xona kamerasida yuz substream'da juda kichik.
    # app/services/camera_roles.py, app/jobs/attendance_ai.py, frame_grabber.py.
    attendance_all_cameras: bool = False
    # Kelish ISTALGAN kamerada (2026-09-26): umumiy yuz tekshiruvi (unified
    # face sweep) barcha kameralarni aylanadi va kunning birinchi aniq tanilishi
    # "keldi" + o'sha soat bo'ladi. Doimiy kuzatuvchi faqat kirish eshiklarida.
    attendance_any_camera: bool = True
    # Tarmoq o'tkazuvchanligi cheklangan: 107 ta 4K asosiy oqim bir vaqtda
    # ochilganda (2026-09-19 03:45) 69 kamera, jumladan kirish eshiklari ham,
    # asosiy oqimni ololmay substream'ga tushdi. Shuning uchun:
    #   * kirish/chiqish/perimetr kuzatuvchilari darhol, xona kameralari esa
    #     room_watcher_start_delay_seconds + tasodifiy 0..room_watcher_start_spread_seconds
    #     keyin boshlanadi — kirish eshigi o'tkazuvchanlikni birinchi oladi;
    #   * asosiy oqimi ishlamagan xona kamerasi uzoqroq (ai_room_main_stream_retry_seconds)
    #     substream'da qoladi, kirish kamerasi esa tez (ai_entrance_main_stream_retry_seconds)
    #     qayta urinadi.
    room_watcher_start_delay_seconds: float = 60.0
    room_watcher_start_spread_seconds: float = 90.0
    ai_room_main_stream_retry_seconds: float = 3600.0
    # Xona kameralari ham asosiy (4K) oqimni o'qiydimi. Productionda
    # (2026-09-19 04:35) tarmoq ~40 ta asosiy oqimdan ko'pini ko'tarmadi:
    # xona kameralari qo'shilgach, 8 ta kirish kamerasining hammasi
    # substream'ga siqib chiqarildi. Standart — yo'q: kirish/perimetr asosiy
    # oqimda, xonalar substream'da (kameraga yaqin odam baribir taniladi).
    ai_room_cameras_main_stream: bool = False
    # Faqat DARS bo'yicha davomat va o'qituvchilar kuzatuvida: dars
    # boshlanganidan necha daqiqagacha kirish "o'z vaqtida" hisoblanadi
    # (kirish eshigidan auditoriyagacha yurish uchun).
    attendance_late_to_lesson_grace_minutes: int = 5
    # Bir kamerada shu daqiqadan qisqa tanaffus bilan ketma-ket yuz
    # tanishlar bitta "tashrif"ga birlashtiriladi (app/models/presence_visit.py).
    presence_visit_gap_minutes: int = 10
    # TT kriteriya 9 ("Darsdan/ishdan erta ketish") — pure rule-based, no
    # extra model needed: a day's check_out (already tracked as "last seen"
    # by upsert_attendance_from_recognition above) earlier than this is
    # flagged early_leave in GET /api/attendance/{id} — see
    # app/routers/attendance.py's _to_out().
    attendance_early_leave_cutoff: str = "16:00"
    # A check_out only minutes (even seconds) after check_in doesn't mean
    # someone worked a while then left early — it usually means a camera
    # (often just one entrance camera) caught them once, briefly, and never
    # saw them again for the rest of the day (no continuous multi-camera
    # tracking exists here — see attendance_ai.py's module docstring).
    # Require at least this much of a gap before early_leave is trusted as
    # a real "was present, then left" signal rather than a single sighting.
    attendance_early_leave_min_presence_minutes: int = 15

    # Davomat: "kelmadi" (absent) belgilash — app/jobs/absence_marker.py.
    # Bu ish qo'shilgunga qadar HECH BIR kod 'kelmadi' yozmasdi: tizim
    # faqat kamera TANIGAN odamni qayd qilardi, kelmagan odamda esa umuman
    # yozuv bo'lmasdi, shuning uchun barcha panellarda "Kelmaydiganlar"
    # doim 0 ko'rinardi.
    #
    # mark_after — ish kuni tugagach belgilanadi (mahalliy vaqt): soat
    # 09:00 da "kelmadi" deb yozish shunchaki noto'g'ri bo'lardi, odam
    # yo'lda bo'lishi mumkin. working_weekdays — ISO kunlar (Du=1..Ya=7);
    # standart 1-6, ya'ni dam olish kuni faqat yakshanba.
    attendance_absence_marking_enabled: bool = True
    attendance_absence_mark_after: str = "20:00"
    # Ota-onalarga "kelmadi" xabari shu soatdan keyin (va 06:00 gacha) yuborilmaydi.
    parent_notify_quiet_after: str = "22:00"
    attendance_working_weekdays: str = "1,2,3,4,5,6"
    attendance_absence_marking_interval_seconds: int = 900
    # Shu kuni ro'yxatdagi odamlarning kamida shuncha ulushi tanilgan
    # bo'lsagina qolganlar "kelmadi" deb belgilanadi (tur bo'yicha alohida
    # — xodim va talaba). Aks holda kameralar ishlamagan kun butun jamoani
    # "kelmadi" qilib qo'yardi. 0 — himoya o'chiq.
    attendance_absence_min_coverage: float = 0.3

    # TT kriteriya 3 ("Notekis/kechki vaqtda kirish") — also pure rule-based:
    # a face-recognized check-in outside [start, end) raises a real Event
    # (module_code=3), same as any other AI-detected incident.
    attendance_off_hours_start: str = "07:00"
    attendance_off_hours_end: str = "20:00"
    # Camera.is_entrance cameras get a multi-frame burst instead of one
    # sampled frame — see app/models/camera.py's is_entrance docstring and
    # app/jobs/attendance_ai.py's run_attendance_ai_sweep_once. Mirrors
    # app/services/frame_grabber.py's grab_frame_burst signature/defaults
    # used by vision_ai.py's sleep confirmation, though attendance doesn't
    # need majority voting — ANY frame matching a person is enough to
    # credit them (upsert_attendance_from_recognition is idempotent per
    # person per day), since the goal is maximizing recall for someone
    # only briefly in frame, not filtering a noisy classification.
    attendance_entrance_burst_frame_count: int = 3
    attendance_entrance_burst_gap_seconds: float = 1.0
    # unified_face_sweep only checks each camera once every
    # unified_face_sweep_interval_seconds (30s default) - fine for a
    # classroom where people linger, but an entrance/exit camera's whole
    # point is someone passing through in a couple of seconds. If that
    # brief window doesn't land inside one of the periodic ~2-3s bursts,
    # they're missed entirely, not just poorly recognized. Entrance/exit
    # cameras get their own much faster, narrowly-scoped check instead
    # (see run_entrance_exit_attendance_sweep_once) - unified_face_sweep
    # still handles crowd/unauthorized/sleep on these same cameras at its
    # normal cadence, and still handles attendance for every other camera.
    #
    # 2026-09-18 dan: har kirish/chiqish kamerasining DOIMIY kuzatuvchisi
    # bor (app/jobs/attendance_ai.py, _watch_entrance_camera) — har yangi
    # kadr kelishi bilan tahlil qilinadi. Bu oraliq endi faqat dispetcher
    # sur'ati: kuzatuvchilarni boshlash/yangilash/to'xtatish va natijani
    # yig'ish. Burst sozlamalari (yuqorida) faqat bir martalik tekshiruvda.
    entrance_exit_attendance_interval_seconds: int = 6

    # Entrance/exit cameras get their OWN concurrency budget
    # (app/jobs/sweep_concurrency.py's entrance_exit_sweep_slot), separate
    # from the shared ai_global_sweep_concurrency pool every other sweep
    # draws from. Found as a real, measured production bug: this sweep's
    # 6s cadence + 3-frame burst-grab per camera (~2-4s slot-hold each)
    # meant it was recurring 5x more often than the 30s unified_face_sweep
    # and repeatedly grabbing a large share of the shared 18-slot pool,
    # starving unified_face_sweep's ability to keep its own cadence for
    # every other camera — measured median per-camera sweep gap of ~101s
    # against a configured 30s, with one camera going 42 minutes unswept.
    # A separate, small pool sized to this sweep's own (much smaller)
    # camera count means it can run at full speed without taking capacity
    # away from anything else.
    #
    # Doimiy kuzatuvda slot faqat kadr TAHLILI paytida olinadi (kutish
    # CPU olmaydi) — ya'ni bu bir vaqtdagi eshik tahlillari chegarasi.
    entrance_exit_sweep_concurrency: int = 6
    # Ish vaqtida kirish kameralari shuncha daqiqa birorta kadr tahlil
    # qilmasa — panelda kritik ogohlantirish (app/services/ai_watchdog.py).
    # 0 — o'chiq.
    ai_watchdog_minutes: int = 10
    # Harakat bo'lmasa tahlil yo'q (app/services/motion_gate.py). Kadr 1/8
    # o'lchamda oldingisi bilan solishtiriladi: piksel yorqinligi
    # `pixel_delta` dan ko'p o'zgargan piksellar ulushi `min_changed_fraction`
    # dan kam bo'lsa — to'liq yuz tahlili o'tkazib yuboriladi. Baribir har
    # `max_skip_seconds` da bir kadr tahlil qilinadi.
    motion_gate_enabled: bool = True
    motion_gate_pixel_delta: int = 18
    motion_gate_min_changed_fraction: float = 0.003
    motion_gate_max_skip_seconds: float = 30.0
    # Kuzatuvchi shuncha soniya hech qadam qo'ymasa (kadr kutish ham, tahlil
    # ham tugamasa) — u qotgan hisoblanadi va qayta ishga tushiriladi.
    entrance_watcher_stall_seconds: int = 180

    # TT kriteriya 20 ("Talabaning uxlab qolishi") — app/jobs/vision_ai.py.
    # Same camera pool as attendance_ai (faol + reachable), separate sweep
    # since it checks EVERY face in frame (attendance only matches the
    # single largest face). sleep_dedup_minutes avoids re-raising an Event
    # every tick for a person who stays asleep across many sweeps.
    vision_ai_interval_seconds: int = 30
    sleep_dedup_minutes: int = 15
    # PERCLOS-style multi-frame confirmation (app/jobs/vision_ai.py) —
    # replaces the earlier fixed 2-frame "asleep in both" check with a
    # majority vote across a short burst, on the same premise (a blink
    # doesn't last multiple seconds) but statistically sturdier: one noisy
    # frame out of 4 no longer flips the result either way. Frame count is
    # a real cost (each is an InsightFace inference call — see
    # face_recognition_inference_concurrency), so raising it trades
    # accuracy for load; 4 frames over ~3s was picked as a reasonable
    # balance, not measured against labeled footage.
    sleep_confirmation_frame_count: int = 4
    # Uyqu (#20) faqat jadvaldagi dars davom etayotgan auditoriyada tekshiriladi
    # (app/jobs/unified_face_sweep.py). Bo'sh xonada yoki tanaffusda 4 kadrli
    # burst — CPU isrofi va yolg'on signal manbai edi.
    sleep_only_during_lessons: bool = True
    sleep_confirmation_gap_seconds: float = 1.0
    sleep_confirmation_majority_ratio: float = 0.75

    # Ko'z holatini o'lchash uchun yuzning eng kichik balandligi (piksel).
    #
    # Nega piksel, kadr ulushi emas: talab ko'z sohasidagi haqiqiy
    # aniqlikka bog'liq, kadr 4K yoki 432p bo'lishiga emas.
    #
    # 80 qayerdan olindi — production'dagi 89 ta "uxlab qolish"
    # signalining rasmlari o'lchandi:
    #
    #   19 tasida kadrda yuz umuman yo'q edi
    #   qolgan 70 tasida: min=8px, mediana=28px, 75%=70px, max=188px
    #
    # Ochiq ko'z yuz balandligining taxminan 1/25 qismi. 28 piksellik
    # yuzda bu ~1 piksel: bitta landmark xatosi hukmni teskarisiga
    # o'zgartiradi. 80 pikselda ~3 piksel bo'ladi — bu ham ko'p emas,
    # lekin o'lchov ma'noga ega bo'ladigan quyi chegara.
    #
    # Bu modulni "aniq" qilmaydi. U shunchaki mumkin bo'lmagan
    # o'lchovlarni to'xtatadi — ular 89 tadan 58 tasi edi.
    sleep_min_face_height_px: int = 80

    # Biometrik ro'yxatdan o'tishdagi tiriklik tekshiruvi
    # (app/services/head_pose.py). Odam kameraga qarab boshini chapga va
    # o'ngga buradi; har bir bosqich server tomonida tekshiriladi.
    #
    # front_tolerance — "to'g'riga qaragan" deb hisoblanadigan oraliq.
    # 0,16 tabiiy: hech kim boshini ideal to'g'ri ushlab turmaydi, va
    # juda tor oraliq odamni bir necha soniya qimirlatib qo'yardi.
    enrollment_front_tolerance: float = 0.16
    # turn_threshold — burilish tasdiqlanadigan chegara. Bundan past
    # burilish "oraliq holat" deb qaytariladi: yetarli burmagan odam
    # tasdiq olmasligi kerak, aks holda tekshiruv shunchaki bezak
    # bo'lib qolardi.
    enrollment_turn_threshold: float = 0.34
    # Yuz shuncha pikseldan baland bo'lishi kerak. Kichik yuzda landmark
    # nuqtalari orasidagi farq shovqindan ajralmaydi.
    enrollment_min_face_height_px: int = 110
    # Bosqich tasdiqlanishi uchun ketma-ket shuncha kadr mos kelishi
    # kerak — bir lahzalik tasodifiy burilish hisobga olinmaydi.
    enrollment_stable_frames: int = 2

    # TT kriteriya 22 ("O'qituvchining darsga aniq kelishi") —
    # app/jobs/teacher_punctuality_ai.py. Only affects LessonSession rows
    # that have teacher_id/camera_id/scheduled_start_time set (no
    # scheduling UI exists yet to populate these, so this is a no-op
    # until a schedule is actually entered). grace_minutes is how long
    # after scheduled_start_time a teacher has to be seen before the
    # check runs and (if not seen) raises an Event.
    teacher_punctuality_interval_seconds: int = 60
    teacher_punctuality_grace_minutes: int = 10
    # Tekshiruv muddati (dars boshi + grace) shundan ko'p o'tgan dars
    # HOZIRGI kadr bilan tekshirilmaydi: o'tgan sana bilan import
    # qilingan jadval "o'qituvchi kelmadi" degan yolg'on signallar
    # to'lqinini keltirardi. Bunday darslar tekshirilmagan holda yopiladi.
    teacher_punctuality_check_window_minutes: int = 30

    # TT kriteriya 1 ("Notanish/begona shaxsni aniqlash") —
    # app/jobs/unauthorized_person_ai.py.
    unauthorized_person_ai_interval_seconds: int = 30
    unauthorized_person_dedup_minutes: int = 5
    # InsightFace's detector has no liveness/depth check — a printed photo
    # on a wall (a noticeboard, an ID card, a poster) reads as a real face
    # just like a person does, and being flat and permanent, it passes the
    # two-frame confirmation every single time (unlike a genuine one-off
    # detection glitch). A real person close enough to a hallway camera to
    # be a security-relevant sighting has a face that's a meaningfully
    # larger fraction of the frame than a small photo on a distant wall.
    # Faces shorter than this fraction of the frame's height are ignored
    # for unauthorized-person purposes (still detected/matched normally
    # for attendance elsewhere, where a false match just costs nothing).
    unauthorized_min_face_height_fraction: float = 0.08
    # Bazadagi eng yaqin odamga shundan ko'p o'xshagan yuz begona emas
    # (yumshoq davomat chegarasi bilan bir xil) va ikki kadrdagi yuz shu
    # o'xshashlikdan boshlab "o'sha odam" hisoblanadi.
    unauthorized_known_similarity: float = 0.42
    unauthorized_pair_same_person: float = 0.40

    # Kunduzgi ko'rib chiqish rejimi (app/services/unknown_sightings.py).
    # Ogohlantirish oynasidan TASHQARIDA notanish yuz signal emas —
    # rasmi bilan ro'yxatga tushadi; operator "talaba" yoki "begona"
    # deydi. Sabab: talabalarning ko'pchiligining yuzi hali tizimda yo'q,
    # kunduzgi signal ularni "begona" deb chalardi.
    unknown_review_enabled: bool = True
    # Sinf va boshqa ichki kameralar ham ro'yxatga yozadi — davomat
    # skaneri ALLAQACHON topgan yuzlardan (qo'shimcha kadr/tahlil yo'q).
    unknown_review_all_cameras: bool = True
    # Ro'yxatga faqat tanib olsa bo'ladigan yuz tushadi: operator mayda
    # yoki pastga qaragan yuzni baribir taniy olmaydi, ro'yxat esa
    # axlatga to'lib, foydasi yo'qoladi.
    unknown_review_min_face_px: int = 40
    # Kamera kuzatuvchilarining sur'ati (app/services/camera_pacing.py):
    # yaroqli yuz ko'rmagan kamera kutadi, bo'shagan AI vaqti yuz
    # ko'rayotgan kameralarga o'tadi. Kirish/chiqish kameralari kutmaydi.
    # Video arxivi (app/services/recording.py). ~52 Mbit/s barcha
    # substreamlar uchun — soatiga ~23,5 GB; 4 soat ≈ 100 GB (2026-09-24
    # kelishilgan byudjet). Disk bo'sh joyi `recording_min_free_percent`
    # dan kamaysa yozuv avtomatik to'xtatiladi (app/jobs/event_clips.py).
    recording_enabled: bool = False
    recording_retention_hours: int = 4
    recording_segment_minutes: int = 5
    recording_min_free_percent: float = 12.0
    recordings_dir: str = "/recordings"
    mediamtx_playback_port: int = 9996
    # Hodisa klipi: hodisadan oldin/keyin necha soniya, MinIO'da necha kun.
    event_clip_enabled: bool = True
    event_clip_before_seconds: int = 15
    event_clip_after_seconds: int = 25
    event_clip_retention_days: int = 30
    event_clip_max_bytes: int = 40_000_000
    # Arxiv videosi havolasining amal qilish muddati (imzolangan URL).
    archive_link_ttl_seconds: int = 3600
    pacing_enabled: bool = True
    pacing_idle_after: int = 3
    # 2026-09-26: 20/150 -> 5/20 s. Protsessor bo'sh (32 yadrodan ~4 tasi band),
    # uzoq kutishda esa odam tahlilgacha kadrdan chiqib ketardi.
    pacing_idle_base_seconds: float = 5.0
    pacing_idle_max_seconds: float = 20.0  # entrance_watcher_stall_seconds dan kichik
    # Kutayotgan kamerada harakat paydo bo'lsa, kutish to'xtatiladi — odam
    # 150 s kutmasdan 1-3 s da tahlil qilinadi. Faqat bugun kamida bitta
    # yaroqli yuz bergan kamerada (orqa tomondan ko'radigan koridor harakat
    # tufayli uyg'onib, CPU'ni behuda yemasin) va eng ko'pi har
    # pacing_motion_min_seconds da bir marta.
    pacing_motion_wake: bool = True
    pacing_motion_min_seconds: float = 1.5
    # Harakat bilan uyg'onish barcha kameralarda (faqat yuz bergan kameralarda emas).
    pacing_motion_wake_any: bool = True
    # Harakat hududida aniqlash (app/services/motion_gate.py, motion_box):
    # kadrning faqat o'zgargan qismi (+hoshiya) detektorga beriladi. Aniqlash
    # vaqti piksellar soniga mutanosib — odam kadrning 30% ida bo'lsa,
    # tahlil ~3 barobar tez. To'liq kadr baribir motion_gate_max_skip_seconds
    # da bir marta (qimirlamay o'tirganlar ham ko'rilsin).
    motion_roi_enabled: bool = True
    motion_roi_margin: float = 0.35  # hudud o'lchamiga nisbatan har tomonga
    motion_roi_max_area: float = 0.6  # bundan katta hudud — to'liq kadr arzonroq
    # Real vaqtdagi skaner (app/services/live_focus.py). Operator so'rovlari
    # to'xtagach kamera shuncha soniyadan keyin odatdagi navbatga qaytadi.
    live_focus_ttl_seconds: float = 12.0
    live_focus_poll_seconds: float = 1.0
    live_result_ttl_seconds: int = 15
    # Kuzatuvchi natijasi shundan eski bo'lsa ishlatilmaydi.
    live_result_max_age_seconds: float = 5.0
    # Birinchi so'rovda kuzatuvchi natijasini shuncha kutadi; kelmasa API
    # kadrni o'zi tahlil qiladi (ai-worker o'chiq yoki kamera kuzatilmaydi).
    live_result_first_wait_seconds: float = 4.0
    # Brauzerdagi HLS kadrining vaqt belgisi (EXT-X-PROGRAM-DATE-TIME) AI
    # o'qigan kadrnikidan qancha KEYIN qo'yiladi (ms): video MediaMTX'da
    # brauzer uchun qayta kodlanadi (runOnDemand ffmpeg), AI esa kameradan
    # to'g'ridan-to'g'ri o'qiydi. Ramka shu farqqa tuzatiladi.
    live_overlay_clock_offset_ms: int = 0
    # Operator kuzatayotgan kameraning yuz belgilari asosiy (4K) oqimdan
    # olinadi. O'lchov (2026-09-24, "2-xona", ~20 talaba): kichik oqimda
    # 10 yuzdan faqat 3 tasi tahlilga yaradi (10-20 px), 4K da — 10 tasi
    # ham (37-125 px). Faqat BITTA kuzatilayotgan kamera uchun, va
    # o'quvchi stream_cache_idle_timeout o'tgach o'zi yopiladi.
    live_detection_main_stream: bool = True
    live_detection_main_wait_seconds: float = 6.0
    # Bir kunda shu o'xshashlikdan yuqori yuzlar bitta qatorga yig'iladi.
    # ArcFace'da bir odamning ikki kamera kadri odatda 0.45-0.70.
    unknown_merge_similarity: float = 0.5
    # Kunlik qator chegarasi — noto'g'ri sozlangan kamera ro'yxatni
    # ko'mib tashlamasin.
    # 2026-09-24: 600 lik chegara kun o'rtasida to'lib, keyingi yuzlar tashlab
    # yuborildi. Takroriy notanishlar (app/services/unknown_clusters.py)
    # butun kunni ko'rishi kerak.
    unknown_daily_cap: int = 1500
    # Takroriy notanishlar: bir odam deb guruhlash chegarasi (ArcFace'da bir
    # odamning ikki kamera kadri odatda 0.45-0.70), guruhlashga olinadigan
    # eng kichik yuz, "bu X emasmi?" ishorasi chegarasi va biriktirishda
    # galereyaga qo'shiladigan qo'shimcha namunalar soni.
    unknown_cluster_similarity: float = 0.48
    unknown_cluster_min_px: int = 40
    unknown_hint_similarity: float = 0.30
    unknown_cluster_gallery_samples: int = 8
    # Kesilgan rasmga yuz atrofidan qo'shiladigan hoshiya (yuz o'lchamiga
    # nisbatan) — operator odamni tanishi uchun soch/kiyim ham ko'rinsin.
    unknown_crop_margin: float = 0.6
    # "Talaba" deb belgilangan yuz odamning asl rasmiga shundan kam
    # o'xshasa biriktirilmaydi: operator xato odamni tanlagan bo'lishi
    # mumkin (galereyaga begona yuz qo'shilsa, kamera uni o'sha odam deb
    # tanib qoladi).
    unknown_assign_min_similarity: float = 0.25
    # ── Yuz tekshiruvi navbati (app/services/face_review.py) ────────────
    # Qat'iy chegaradan (attendance_ai_match_threshold) past, lekin shundan
    # yuqori moslik — "kulrang zona": 2026-09 o'lchovida haqiqiy mosliklar
    # ko'pincha 0.42-0.50 da qolardi. Ular operatorga ko'rsatiladi.
    face_review_enabled: bool = True
    face_review_min_similarity: float = 0.42
    # Eng yaqin nomzod ikkinchisidan shuncha uzoq bo'lmasa — kimligi noaniq,
    # operatorga "shumi?" deb ko'rsatishning ma'nosi yo'q.
    face_review_min_margin: float = 0.05
    # Kunlik yangi qator chegarasi — navbat odam ko'ra oladigan hajmda qolsin.
    face_review_daily_cap: int = 800

    # YOLOv8 object detection (app/services/object_detection.py) — TT
    # kriteriya 19 (dars diqqati) telefon signali uchun ishlatiladi. See
    # face_recognition_gpu_enabled/inference_concurrency for the same
    # pattern applied to InsightFace; this is the object-detection
    # equivalent, a separate knob since the two models have independent
    # resource costs.
    object_detection_model_path: str = "yolov8n.pt"
    object_detection_gpu_enabled: bool = False
    object_detection_inference_concurrency: int = 2

    # Telefon aniqlash ishonchi. #16 ("Imtihonda telefondan foydalanish")
    # olib tashlangandan keyin uni ishlatadigan yagona joy — #19
    # ("Talabaning darsga diqqati"), u yerda telefon ko'rinishi diqqat
    # ballini pasaytiruvchi signal sifatida qoladi.
    phone_detection_confidence: float = 0.5

    # mediapipe Pose Landmarker (app/services/pose_detection.py) — shared
    # by TT kriteriya 2 (taqiqlangan zona), 10 (oq xalat), 21 (o'qituvchi
    # faolligi). Same pattern as object_detection_*/face_recognition_*
    # above, a separate knob since each model has independent resource
    # costs.
    pose_detection_model_path: str = "pose_landmarker_lite.task"
    pose_detection_inference_concurrency: int = 2
    pose_detection_max_poses: int = 5
    # "auto" — mediapipe, agar protsessor AVX ni qo'llasa; AVX yo'q bo'lsa
    # YOLOv8-pose (production serverdagi holat). "mediapipe"/"yolo" — majburan.
    pose_detection_backend: str = "auto"
    pose_detection_yolo_model_path: str = "yolov8n-pose.pt"
    pose_detection_yolo_confidence: float = 0.4
    # Ketma-ket shuncha marta mediapipe ishchi jarayoni yiqilsa, jarayon
    # umrining oxirigacha YOLOv8-pose ga o'tiladi (qayta-qayta yiqilib CPU
    # yeyish o'rniga).
    pose_detection_max_worker_crashes: int = 3

    # TT kriteriya 19 ("Talabaning darsga diqqati") va 21 ("O'qituvchi
    # faolligi") — app/jobs/lesson_quality_ai.py. lesson_duration_minutes
    # defines the "active window" after scheduled_start_time during which
    # both scores are sampled — no LessonSession end-time field exists,
    # so this is a configured assumption (typical class length), not
    # read from real schedule data.
    lesson_quality_ai_interval_seconds: int = 30
    lesson_duration_minutes: int = 90

    # Dars jadvali asosidagi davomat — app/jobs/lesson_attendance.py.
    #
    # min_sightings: talaba dars davomida kamida shuncha marta
    # ko'rinishi kerak. Bitta moslik yetarli emas — yonidan o'tib ketgan
    # odam ham, yuz mosligining xatosi ham bitta kadrda ko'rinishi
    # mumkin. 90 daqiqalik darsda sweep ~45 s da bir ishga tushadi, ya'ni
    # haqiqatan o'tirgan talaba o'nlab marta ko'rinadi va bu chegara
    # unga to'sqinlik qilmaydi; tasodifiy moslik esa takrorlanmaydi.
    lesson_attendance_min_sightings: int = 3
    # Bitta dars kamerasi necha soniyada bir tahlil qilinadi (app/jobs/lesson_quality_ai.py).
    # 90 daqiqalik darsda 300 s — 18 namuna: diqqat/faollik o'rtachasi va
    # 3 ta ko'rinishli dars davomati uchun yetarli, CPU esa ~7 barobar kam.
    lesson_sample_interval_seconds: int = 300
    # Yakunlash ishi tugagan darslarni qidiradi — tez-tez ishlashi shart
    # emas, lekin dars tugagach hisobot uzoq kutmasligi kerak.
    lesson_attendance_finalize_interval_seconds: int = 300
    # Yakunlanmagan darslar shuncha kun orqaga qidiriladi. Kamerasi
    # hech kimni ko'rmagan dars hech qachon yakunlanmaydi — chegarasiz
    # qidiruv har 5 daqiqada butun semestr jadvalini o'qirdi.
    lesson_attendance_finalize_lookback_days: int = 3
    attention_score_frontal: float = 100.0
    attention_score_not_frontal: float = 40.0
    attention_score_phone_visible: float = 20.0
    teacher_activity_min_visibility: float = 0.5
    # Scales average per-landmark displacement (normalized 0-1 frame
    # coordinates, ~1s apart) into a 0-100 score. Not calibrated against
    # real classroom footage — chosen so a small (~0.1 average landmark
    # movement) reads as a mid-range score, an untuned starting point.
    teacher_activity_scale: float = 500.0

    # DIQQAT — bu son db_pool_size + db_max_overflow (hozir 20+40=60) dan
    # oshib ketmasligi kerak: unified_face_sweep har bir kamera uchun
    # alohida DB sessiyasi ochadi, shuning uchun bu qiymat + entrance_exit
    # (6) + camera_health + API so'rovlari birgalikda pool sig'imidan
    # oshsa, sweep'lar pool_timeout (30s) da kutib qotadi.
    #
    # Max cameras processed concurrently ACROSS ALL AI sweep modules.
    # app/jobs/sweep_concurrency.py — every module shares this one cap so
    # parallel scheduler ticks can't spawn (module_count × N) pipelines.
    #
    # Raised 18 -> 40 after tracing a measured production backlog past
    # face_recognition_inference_concurrency: app/jobs/unified_face_sweep.py's
    # _process_camera holds ONE camera_sweep_slot for its camera's ENTIRE
    # multi-frame sequence, including the deliberate asyncio.sleep() gaps
    # between burst frames (sleep_confirmation_gap_seconds /
    # attendance_entrance_burst_gap_seconds / grab_frame_pair's gap) — up
    # to ~4s of pure waiting, zero CPU, per camera needing both sleep and
    # unauthorized-person checks. With only 18 slots, most of the pool was
    # tied up WAITING rather than computing (confirmed live: `top` showed
    # the container at just ~47% CPU of its cap while the sweep still ran
    # ~140s/round for 107 cameras — not CPU-bound, slot-starved on
    # deliberately-idle time). Raising this doesn't add real compute load
    # the way face_recognition_inference_concurrency does — it lets more
    # cameras' idle gap-waits overlap — so it can go much higher than that
    # setting without a proportional CPU cost. Re-measure via
    # sweep_result_cache timestamps after any change to this number.
    ai_global_sweep_concurrency: int = 40

    # Deprecated alias kept for older .env files — prefer
    # AI_GLOBAL_SWEEP_CONCURRENCY on production servers.
    ai_sweep_camera_concurrency: int = 8

    # Seconds between each AI sweep loop's FIRST tick at startup (see
    # app/main.py's lifespan) — all 16 loops used to fire their first
    # sweep in the same instant, all contending for the same camera/
    # inference semaphores and DB connections at once, then falling back
    # into sync every ~30s after. Staggering only the START time smooths
    # that initial burst; each loop's own steady-state interval (still set
    # independently per job, e.g. attendance_ai_interval_seconds) is
    # unchanged.
    ai_loop_stagger_seconds: float = 2.0

    # InsightFace/ONNX inference. face_recognition_gpu_enabled requests
    # CUDAExecutionProvider first (falls back to CPU automatically if the
    # onnxruntime-gpu package/CUDA drivers aren't present — see
    # app/services/face_recognition.py's _get_app()). Only takes effect if
    # onnxruntime-gpu is installed instead of the CPU-only onnxruntime
    # package (see requirements.txt) — installing the package alone does
    # nothing without also flipping this on.
    face_recognition_gpu_enabled: bool = False
    # How many InsightFace calls run concurrently — this gate
    # (app/services/inference_gate.py's face_inference_gate), not
    # camera_sweep_slot, turned out to be the REAL bottleneck behind a
    # measured production backlog: with 107 cameras and this at 2, median
    # per-camera background-sweep gap was 100-175s against a configured
    # 30s (worst case: one camera unswept for 42+ minutes). Measured the
    # actual cost on this CPU-only production host: a single InsightFace
    # call is ~1.4s. Raising this alone (2 -> 8) wasn't enough, because
    # app/jobs/unified_face_sweep.py's _process_camera was ALSO issuing a
    # camera's own multiple detect_faces() calls (up to 6, for a camera
    # needing both sleep and unauthorized-person checks) strictly
    # sequentially — fixed alongside this, see that function's docstring;
    # it now gathers them concurrently. With that fixed, direct math on
    # the measured per-call cost: 107 cameras x up to 6 calls each / a 30s
    # target needs roughly 30 concurrent slots to keep up. 24 is a
    # calibrated step toward that (not the full 30, kept conservative
    # since this host's real per-call latency under this much concurrency
    # hasn't been measured yet) — re-measure via sweep_result_cache
    # timestamps after deploy and adjust, don't leave this guessed. A real
    # GPU deployment should raise this a lot more (GPUs are built for
    # exactly this kind of concurrent batched throughput) — tune against
    # the actual production GPU's memory and measured latency then, same
    # discipline.
    face_recognition_inference_concurrency: int = 24
    # Bitta ONNX chaqiruvi ichidagi oqimlar soni (app/services/face_recognition.py
    # _limit_session_threads). 0 — onnxruntime standarti: HOSTdagi barcha
    # yadrolar, konteynerning `cpus` chegarasini hisobga OLMAYDI.
    #
    # Productionda o'lchandi (2026-09-15): 32 yadroli host, konteyner cpus: 20,
    # inference_concurrency=24 va cheklanmagan oqimlar — yuklama 110, konteyner
    # doim chegarada (2034%), 6 s lik kirish tekshiruvi 263 s. 24 ta parallel
    # chaqiruvning har biri 32 oqimlik havza ishlatib, 20 yadroni kontekst
    # almashtirishga sarflardi. Umumiy oqimlar ≈ concurrency × shu qiymat —
    # cpus chegarasidan (ffmpeg o'quvchilari ham shu konteynerda!) oshmasin.
    face_recognition_intra_op_threads: int = 2
    # Operator ochgan kamera (PRIORITY_LIVE) uchun alohida "jonli yo'lak":
    # o'sha modellar, lekin ko'proq oqimli ONNX sessiyalar va fon
    # tahlillari band qilgan slotlarni KUTMAYDIGAN zaxira joylar
    # (app/services/inference_gate.py, face_recognition._live_app).
    # O'lchov (2026-10-06, production, load ~17/32): 2 oqim — detektor
    # 1396 ms, 3 yuz embedding 701 ms, landmark 183 ms/yuz; 8 oqim — 549,
    # 319, 45 ms. Ilgari yuz chiqqan kadr natijasi 2.3-4.1 s kechikardi
    # (navbat + 2 oqim). Zaxira joylar soni = bir vaqtda jonli tahlil
    # qilinadigan kadrlar (odatda bitta operator — bitta kamera);
    # 0 — yo'lak o'chiq, jonli ham umumiy navbatda.
    face_live_intra_op_threads: int = 8
    face_live_reserved_slots: int = 2
    # /royxatdan-otish (pose-check, submit) hovuzidagi oqimlar — har worker'da.
    # Jonli yo'lakdan alohida: u yerda 2 ta joy, ro'yxatdan o'tishda esa bir
    # vaqtda o'nlab telefon (2026-10-07: 80+ so'rov/daqiqa).
    face_enrollment_workers: int = 6
    # Pose-check detektor kirishining uzun tomoni. Telefon 270x480 kadr
    # yuboradi va yuz kameraga yaqin (>=110 px) — 640 gacha kattalashtirish
    # behuda. O'lchov (2026-10-07, production, 30 rasm): 640 — 0.57 s,
    # 320 — 0.15 s, yo'nalish va "yaqinlik" natijasi 30/30 bir xil.
    enrollment_pose_det_max_side: int = 320
    # CPU'da INT8 modellar (app/services/face_recognition.py _int8_model_file):
    # AVX'siz protsessorda ArcFace 1.75x, detektor 1.3x tez, vektorlar fp32
    # bazasi bilan mos (cos ~0.994). GPU yoqilganda e'tiborga olinmaydi.
    face_recognition_int8: bool = True
    face_detection_int8: bool = True
    # Klassik OpenCV hisoblari (yong'in, optik oqim, xalat/niqob rangi) uchun
    # oqimlar soni — app/services/cpu_pool.py. Bular ilgari event loop'da
    # ketma-ket bajarilardi; havza ularni parallel qiladi, lekin CPU'ni
    # yuz tanishdan tortib olmasligi uchun kichik qoldiriladi.
    cv_thread_pool_size: int = 4
    # PyTorch (YOLO obyekt va poza) va OpenCV ichki oqimlari —
    # app/services/thread_limits.py. Ikkalasi ham standart bo'yicha HOSTdagi
    # barcha yadrolarni ko'radi (konteynerning `cpus` kvotasini emas):
    # productionda 8 ta parallel YOLO chaqiruvining har biri 32 oqimli havza
    # ochardi, ya'ni 20 yadroli kvotada yuzlab oqim — CFS throttling butun
    # konteynerni, jumladan API javoblarini ham sekinlashtirardi.
    # 0 — kutubxona standarti (dasturchi kompyuteri uchun), musbat son —
    # aniq chegara. OMP/OPENBLAS/MKL oqimlari esa env orqali beriladi
    # (deploy/env.production.scale), chunki ular kutubxona yuklanishidan
    # OLDIN o'qiladi.
    ai_torch_threads: int = 0
    # -1 — OpenCV standarti; 0 — OpenCV ichki parallelligi o'chiriladi;
    # musbat son — aniq chegara.
    cv_internal_threads: int = -1

    # Persistent per-camera frame cache (app/services/stream_cache.py) —
    # replaces spawning a fresh ffmpeg process on every single frame grab
    # with one long-lived ffmpeg reader per camera that continuously
    # decodes frames and keeps only the latest one in memory.
    # stream_cache_max_age_seconds: how stale a cached frame is allowed to
    # be before it's treated as "stream stalled" (same as a failed grab).
    # stream_cache_idle_timeout_seconds: a camera's reader is stopped (and
    # its ffmpeg process killed) after this long with no sweep loop asking
    # for its frames — avoids leaking a live decode pipeline per camera
    # that was deactivated or removed.
    stream_cache_max_age_seconds: float = 15.0
    stream_cache_idle_timeout_seconds: float = 300.0
    stream_cache_capture_fps: float = 2.0
    # Har o'quvchi saqlaydigan oxirgi HAR XIL kadrlar soni (kadr tarixi).
    # Kalit kadr ~1 s da bo'lsa, 6 ta kadr ~5-6 s ni qamraydi — uyqu burst'i
    # (4 kadr, 1 s oraliq) va juftliklar yangi kadr kutmasdan olinadi.
    stream_cache_history_frames: int = 6
    # A camera's real stream runs at its native fps (e.g. 25) but
    # stream_cache_capture_fps only needs ~1-2 of those per second —
    # ffmpeg was still decoding EVERY incoming frame just to throw away
    # all but the sampled ones (measured: ~96% of decode work discarded).
    # -skip_frame nokey tells the decoder to skip non-keyframe (P/B)
    # packets entirely, decoding only I-frames — which is exactly what a
    # 1-2fps sample needs, PROVIDED the camera's keyframe interval (GOP)
    # is short enough that a fresh I-frame always arrives within
    # stream_cache_max_age_seconds. Verify with ffprobe before enabling
    # fleet-wide (frame=key_frame over a short read_interval) — a camera
    # with a long GOP would otherwise serve stale frames. Off by default
    # since that verification is camera/fleet-specific, not something
    # this code can confirm for itself.
    stream_cache_keyframes_only: bool = False

    # --- Buzilgan kadrni rad etish (app/services/frame_quality.py) ---
    #
    # Piksel shu qiymatdan yorug' bo'lsa "oq" hisoblanadi. 250 ataylab
    # qattiq: dekodlash shikasti deyarli sof oq (255) blok beradi, oddiy
    # yorug' devor yoki quyoshli pol esa bunchalik yuqoriga chiqmaydi.
    frame_corruption_white_level: int = 250
    # Kadr maydonining necha ulushini bitta yaxlit oq blok egallasa,
    # kadr shikastlangan deb hisoblanadi.
    #
    # 0.04 taxmin emas — production'dan olingan 23 ta hodisa rasmi
    # o'lchandi:
    #
    #   sog'lom 19 ta : eng kattasi 1.8% (yorug' derazali xona)
    #   buzilgan 4 ta : 6.6%, 8.1%, 22.0%, 28.8%
    #
    # Ikki to'plam orasida deyarli 4 barobar bo'shliq bor; chegara
    # o'rtadan olindi, shunda ikkala tomonga ham zaxira qoladi.
    #
    # Xavf: butunlay oqarib ketgan katta deraza ham shu chegaradan
    # oshishi mumkin. Bunday kamera AI uchun "ko'r" bo'lib qolmasligi
    # kerak, shuning uchun stream_cache rad etishlar ketma-ket
    # takrorlansa ogohlantirish yozadi — jimgina yo'qolib qolmaydi.
    frame_corruption_max_flat_block_fraction: float = 0.04
    # Bloklar bir xil joyda turgan deb hisoblanishi uchun kerakli
    # kesishish darajasi (IoU). Deraza kadrdan kadrga deyarli
    # qimirlamaydi, shuning uchun 0.5 ham yetarlicha bo'sh chegara;
    # dekodlash shikasti esa har safar boshqa joyda paydo bo'ladi.
    frame_corruption_persistence_overlap: float = 0.5

    # Kamera "tasvir bermayapti" deb hisoblanishidan oldin oxirgi
    # yaroqli kadrdan qancha vaqt o'tishi kerak (soniya).
    #
    # Kamera erishilishi (last_seen_at) bilan aralashtirmaslik kerak.
    # Bu qiymat ataylab kattaroq: AI sweep'lari har kameraga bir necha
    # o'n soniyada bir marta murojaat qiladi, ba'zi kameralar esa
    # birinchi kadrni berish uchun 25 soniyagacha vaqt oladi
    # (production'da o'lchangan). Juda kichik qiymat sog'lom, lekin
    # sekin kamerani "nosoz" deb belgilab qo'yardi.
    camera_video_stale_seconds: int = 300

    # --- Xulq-atvor modullari uchun ish vaqti oynasi ---
    #
    # Bino bo'sh bo'lganda "tartib-intizom buzilishi" yoki "talaba uxlab
    # qolgan" izlashning ma'nosi yo'q — u yerda kuzatiladigan xulq-atvor
    # umuman mavjud emas. Production'da 17-modul hodisalarining ~30% i
    # 00:00-05:00 oralig'ida yozilgan va tekshirilgan namunalarning
    # HAMMASI bo'sh xona bo'lib chiqdi.
    #
    # Bu ro'yxatda XAVFSIZLIK modullari ataylab YO'Q. Tunda begona shaxs
    # (#1), yong'in (#23), yiqilish (#24), taqiqlangan zonaga kirish (#2)
    # — aynan shular eng muhim bo'ladi. Bu yerdagilar esa faqat odamlar
    # bor joyda ma'noga ega bo'lgan modullar.
    behaviour_hours_enabled: bool = True
    behaviour_hours_start: str = "07:00"
    behaviour_hours_end: str = "21:00"
    # 2026-09-07: ro'yxat qayta ko'rib chiqildi. #5 va #16 olib
    # tashlangan kriteriyalar edi; ularning o'rniga #14 (jang) va #15
    # (chekish) qo'shildi — ikkalasi ham yangi yoqildi va ikkalasi ham
    # aynan shu himoyaga muhtoj: bo'sh binodagi harakat anomaliyasini
    # "jang" deb, tungi soyani "chekish posturasi" deb o'qish mumkin.
    behaviour_hours_module_codes: str = "14,15,17,20"

    @property
    def behaviour_hours_codes(self) -> set[int]:
        return {
            int(part.strip())
            for part in self.behaviour_hours_module_codes.split(",")
            if part.strip()
        }
    # ffmpeg's default is one decode thread per CPU core - fine for a
    # single process, but with one persistent reader PER CAMERA (see
    # stream_cache.py's module docstring) that's core-count-times-camera-
    # count threads all fighting over the same physical cores (measured:
    # 100+ camera readers can add up to several thousand threads for a
    # few dozen actual cores). 0 leaves ffmpeg's own default in place.
    stream_cache_decode_threads: int = 0
    # How long a stream reader gets to decode its first frame before a
    # caller's grab_frame_for_camera() poll gives up early instead of
    # burning its full 8-18s wait budget. Once a reader has run this long
    # with zero frames decoded, it's treated as broken until it proves
    # otherwise (see stream_cache.is_stream_known_broken) — keeps one dead
    # RTSP camera from holding a shared sweep slot for its full per-camera
    # timeout, over and over, on every sweep.
    #
    # 5 -> 15 (2026-09-17): sog'lom oqimning birinchi kadri ham ~5 soniyada
    # keladi (ffmpeg oqimni tahlil qiladi, keyin birinchi KALIT kadrni
    # kutadi) — lokal sinovda aynan shu chegarada tashlab ketilgan.
    # Kirish kameralarining asosiy oqimida (2560x1440, H.265) kalit kadr
    # oralig'i undan ham uzun bo'lishi mumkin.
    stream_broken_grace_seconds: float = 15.0

    # Unified face sweep (app/jobs/unified_face_sweep.py) — one frame grab +
    # one face-detect pass per camera tick, feeding attendance/crowd/unauthorized/
    # sleep modules instead of four independent loops each re-grabbing/re-detecting.
    # When true, the four individual face-based loops are NOT started.
    unified_face_sweep_enabled: bool = True
    unified_face_sweep_interval_seconds: int = 30

    # Optional Redis — shared rate limits (slowapi) + WebSocket pub/sub fan-out
    # across multiple API workers/instances. Unset = in-memory (single instance).
    redis_url: str = ""

    # Central AI scheduler (app/jobs/ai_scheduler.py) — when true, individual
    # per-module asyncio loops are NOT started; one coordinator dispatches sweeps.
    ai_scheduler_enabled: bool = False
    # Jarayonning AI'dagi roli (app/main.py lifespan):
    #   "all"    — eski xatti-harakat: qaysi worker leader qulfini olsa, AI o'shanda;
    #   "api"    — faqat HTTP; AI sweeplari hech qachon bu yerda ishlamaydi;
    #   "worker" — AI uchun alohida konteyner (docker-compose ai-worker). Qulf
    #              band bo'lsa (eski api konteyneri hali ishlayotgan bo'lsa),
    #              bo'shaguncha kutadi — "api" jarayoni uni hech qachon olmaydi.
    # Productionda: api=api, ai-worker=worker. Shunda AI yuki (CPU, GIL,
    # ffmpeg) sayt javoblarini sekinlashtirmaydi va AI qayta ishga tushsa
    # ham sayt uzilmaydi.
    ai_role: Literal["all", "api", "worker"] = "all"
    ai_worker_lock_retry_seconds: float = 10.0
    ai_scheduler_poll_seconds: int = 5
    # Davomatga ustuvorlik (app/jobs/ai_scheduler.py). Productionda bitta
    # AVX'siz CPU'da og'ir evristikalar (poza, optik oqim, rang) bilan kirish
    # kameralaridagi yuz tanish talashardi: 6 s lik kirish tekshiruvi 263 s
    # davom etgan. Odamlar ko'p o'tadigan soatlarda (mahalliy vaqt,
    # "HH:MM-HH:MM" vergul bilan) quyidagi sweeplar pauza qiladi — CPU
    # davomatga beriladi. Kun davomida hammasi odatdagidek ishlaydi.
    attendance_priority_enabled: bool = True
    attendance_priority_windows: str = "07:30-09:30,16:00-18:00"
    attendance_priority_paused_sweeps: str = ""

    # GPU batch inference caps — detect_faces_batch / detect_objects_batch chunk size.
    face_recognition_batch_size: int = 4
    object_detection_batch_size: int = 4

    # FAISS exact IP search when enrolled count >= this threshold (requires faiss-cpu).
    face_match_faiss_min_size: int = 10_000
    # Live detection (public.py) reloads embeddings from DB after this TTL.
    candidate_matrix_cache_ttl_seconds: int = 300
    # AI sweep loops share one matrix per TTL — avoids 10k+ row reads every tick.
    candidate_matrix_sweep_cache_ttl_seconds: int = 300

    # Admin dashboard resource alerts (app/routers/system.py).
    resource_alert_cpu_percent: int = 85
    resource_alert_ram_percent: int = 85
    resource_alert_disk_percent: int = 90
    resource_alert_ffmpeg_count: int = 280

    # AI frame_grabber reads RTSP substream directly (bypasses MediaMTX/HLS).
    ai_use_direct_rtsp: bool = True
    # AI qo'shimcha oqimni kameradan EMAS, MediaMTX relay'idan o'qiydi
    # (rtsp://mediamtx-N:8554/cam-<id>): kameraga bitta ulanish qoladi.
    # 2026-09-19: arzon kameralar parallel RTSP sessiyalarni cheklaydi — 4 ta
    # kamera videodevorda ishlagani holda AI ga umuman kadr bermadi.
    ai_read_via_mediamtx: bool = True
    mediamtx_internal_rtsp_port: int = 8554
    # Hikvision substream — lower bandwidth than /Streaming/Channels/101.
    rtsp_substream_path: str = "/Streaming/Channels/102"
    # Kirish/perimetr kameralarda yuz kichik bo'ladi (768x432 substream) —
    # AI uchun asosiy oqim (101, masalan 2560x1440) ishlatiladi.
    ai_entrance_use_main_stream: bool = True
    ai_entrance_frame_wait_seconds: float = 18.0
    # Asosiy oqim kadr bermasa, kamera shuncha vaqt substream'da ishlaydi,
    # keyin asosiy oqim qayta sinaladi (app/services/frame_grabber.py).
    # Productionda (2026-09-17) 11 ta kirish kamerasidan 7 tasining asosiy
    # oqimi kun bo'yi birorta kadr bermagan — ular davomatdan butunlay
    # chiqib qolgan edi.
    ai_entrance_main_stream_retry_seconds: float = 1800.0

    # MediaMTX horizontal sharding — comma-separated URLs, equal length pairs.
    # Empty = single MEDIAMTX_API_URL / MEDIAMTX_HLS_BASE_URL.
    mediamtx_shard_api_urls: str = ""
    mediamtx_shard_hls_base_urls: str = ""
    # Parallel to mediamtx_shard_hls_base_urls — docker-internal HLS bases for ffmpeg
    # (e.g. http://mediamtx-0:8888,http://mediamtx-1:8888,http://mediamtx-2:8888).
    mediamtx_shard_hls_internal_base_urls: str = ""
    # Jonli video WebRTC orqali (app/routers/public.py, /whep): brauzer SDP
    # taklifini API'ga yuboradi, API uni MediaMTX'ning WHEP manziliga
    # uzatadi. Media esa to'g'ridan-to'g'ri UDP'da (shard'ning
    # webrtcLocalUDPAddress porti). HLS'da tasvir 4-8 s orqada edi, WebRTC'da
    # ~0.3-0.5 s. O'chirilsa brauzer darhol HLS'ga qaytadi.
    webrtc_enabled: bool = True
    mediamtx_webrtc_port: int = 8889

    # Browser HLS: substream (102) is usually H.264 — relay without ffmpeg transcode
    # cuts latency from ~30s to ~3-5s. Set false to force H.264 transcode/scale.
    mediamtx_relay_h264_substream: bool = True
    # Browser HLS needs H.264 — when relay is off, on-demand ffmpeg transcodes.
    mediamtx_transcode_h264: bool = False
    # Kamerama-kamera qaror (app/services/video_gateway.py register_camera_stream):
    # ro'yxatga olishda substream kodeki ffprobe bilan o'qiladi — H.264 bo'lsa
    # to'g'ridan-to'g'ri uzatiladi (transkodsiz, CPU ~0, kechikish GOP'ga
    # teng), aks holda (H.265 yoki o'qib bo'lmadi) transkod qilinadi.
    # Aralash park uchun: scripts/camera_stream_settings.py --faqat-sub
    # --qollash bilan substreamlar H.264 ga o'tkazilgandan keyin yoqiladi,
    # o'tmay qolgan kameralar esa baribir ko'rinadi.
    mediamtx_relay_probe_codec: bool = False
    mediamtx_transcode_height: int = 0
    # 0 = kameradan kelgan tezlikni o'zgartirmaslik. > 0 bo'lsa ffmpeg
    # chiqishni shu FPS ga cheklaydi.
    #
    # Nega muhim: transkodlash JONLI oqim ustida ishlaydi. Enkoder real
    # vaqtga ulgurmasa, u kadrlarni tashlab yubormaydi — chiqish kirishdan
    # har soniyada ko'proq orqada qoladi, ya'ni kechikish TO'PLANADI
    # (production'da 2-3 daqiqagacha o'sgan holat aynan shu). FPS ni
    # ikki barobar kamaytirish enkoder xarajatini ham taxminan ikki
    # barobar kamaytiradi, monitoring devori uchun esa 25fps shart emas.
    #
    # mediamtx_transcode_height ham shu mantiqda: u MANBA balandligidan
    # OSHIB ketmasligi kerak. Substream ~360p bo'lsa, 720 qo'yish tasvirni
    # yaxshilamaydi (yo'q detalni yarata olmaydi), faqat enkoderga ~4
    # barobar ko'p piksel ishini beradi.
    mediamtx_transcode_fps: int = 0
    # Ko'ruvchi ketgandan keyin enkoder qancha ishlab turadi (soniya).
    # Kichikroq qiymat sahifalar orasida yurganda to'planib qolgan
    # enkoderlarni tezroq bo'shatadi.
    mediamtx_transcode_close_after_seconds: int = 20
    # Kalit kadrlar orasidagi masofa (soniya) — KECHIKISHNI BELGILAYDIGAN
    # ASOSIY QIYMAT. MediaMTX HLS segmentini faqat kalit kadrda kesa
    # oladi, shuning uchun segment uzunligi = shu qiymat, pleyer esa
    # butun segment yozilishini kutadi. libx264 standarti 250 KADR
    # (soniya emas): 12 fps da bu 20.8 soniyalik segment demakdir —
    # production'da aynan shu o'lchangan. 1 soniya qo'yilsa,
    # mediamtx.yml'dagi hlsSegmentDuration: 1s va hlsPartDuration: 200ms
    # (LL-HLS) nihoyat ishlay boshlaydi.
    mediamtx_transcode_keyframe_seconds: float = 1.0

    # Monitoring devori (MonitoringPage) tizimga kirishni talab qiladimi.
    #
    # Nega sozlama, nega darhol qat'iy emas: bu sahifa kodda ataylab
    # "public" deb qurilgan va situatsion markazdagi katta ekranda
    # doimiy ochiq turishi mumkin. Uni to'satdan yopish o'sha ekranni
    # o'chirib qo'yadi. Shuning uchun himoya standart bo'yicha YOQILGAN
    # (auditda aniqlangan: token'siz ham 107 ta kameraning jonli
    # tasviri ko'rinardi), lekin bitta muhit o'zgaruvchisi bilan
    # darhol qaytarib bo'ladi.
    #
    # DIQQAT: bu faqat API'ni himoyalaydi. Video oqimlarining o'zi
    # nginx orqali MediaMTX'dan uzatiladi va u alohida himoya talab
    # qiladi — kamera ro'yxati yopilgani bilan UUID'ni bilgan odam
    # oqimni baribir ocha oladi.
    public_monitoring_requires_auth: bool = True

    # "Notanish shaxs" (1-modul) ishlashi uchun bazada kamida shuncha
    # tasdiqlangan yuz bo'lishi kerak.
    #
    # Nega kerak: modul "bu odam bazada YO'Q" degan xulosa chiqaradi.
    # Baza deyarli bo'sh bo'lsa, bu xulosa hech narsa anglatmaydi —
    # binodagi HAR BIR odam begona bo'lib chiqadi. Production auditda
    # aynan shu holat topilgan: bazada 3 ta tasdiqlangan yuz bor edi va
    # modul 134 ta signal bergan, ularning 45% i bitta kameradan, 37
    # tasi esa bino bo'sh bo'lgan tunda.
    #
    # Bu ro'yxatga olish tugagach o'zi hal bo'ladi — modul avtomatik
    # ishlay boshlaydi, hech narsani qo'lda yoqish shart emas.
    unauthorized_min_enrolled: int = 10
    # Begona shaxs (#1) faqat shu joy va vaqtda signal beradi. Talabalarning
    # ko'pi yuzini ro'yxatdan o'tkazmagan, shuning uchun kunduzi bino ichidagi
    # "notanish yuz" deyarli har doim o'z talabamiz — bu signal emas.
    # Oyna "HH:MM-HH:MM" (vergul bilan bir nechta, yarim tundan o'tishi
    # mumkin). Ish kuni bo'lmagan kunlarda (attendance_working_weekdays)
    # kun bo'yi faol. perimeter_only — faqat kirish va perimetr kameralari.
    unauthorized_active_windows: str = "19:00-07:00"
    unauthorized_perimeter_only: bool = True

    # Signal oqimi himoyasi (app/services/event_bus.py). Shaxsi aniqlanmagan
    # signallar uchun: bitta kamera×modul soatiga, modul esa butun tizimda
    # soatiga ko'pi bilan shuncha signal yozadi. Ortig'i navbatni to'ldirmaydi.
    event_rate_limit_per_camera_hour: int = 6
    event_rate_limit_per_module_hour: int = 60

    # Shovqinli kamera×modul juftligini avtomatik o'chirish
    # (app/jobs/module_suppression.py): oxirgi window_days kunda kamida
    # min_rejected ta rad etilgan va aniqligi max_precision % dan past bo'lsa.
    suppression_enabled: bool = True
    suppression_interval_seconds: int = 3600
    suppression_window_days: int = 14
    suppression_min_rejected: int = 8
    suppression_max_precision: float = 25.0

    # Sinov rejimidagi modulning aniqligini o'lchash uchun NAMUNA yetarli.
    # Har signalni saqlash bazani va omborni behuda to'ldiradi: chekish
    # moduli (#15) productionda kuniga 1200+ kadr yozardi. Soatlik kvota
    # to'lgach modul o'sha soat oxirigacha umuman tekshirilmaydi
    # (app/jobs/module_status.py) — CPU ham bo'shaydi.
    trial_events_per_module_hour: int = 12
    trial_events_per_camera_hour: int = 2

    # Monitoring markazining qavat gridi uchun miniatyura keshi
    # (app/services/thumbnail_cache.py). Rasm AI baribir oladigan
    # kadrdan tayyorlanadi, shuning uchun gridni ochish kameralarga
    # yangi ulanish qilmaydi; jonli video faqat tanlangan kamerada.
    thumbnail_width: int = 320
    thumbnail_quality: int = 60
    thumbnail_ttl_seconds: int = 300
    # Bitta kameradan miniatyura shu oraliqdan tez-tez siqilmaydi.
    thumbnail_refresh_seconds: int = 20
    # Shu yoshdan eski rasm uchun (sweep tegmagan kamera) bitta kadr
    # so'raladi — global semafor va kamera bo'yicha sovutish ostida.
    thumbnail_stale_seconds: int = 120
    thumbnail_grab_concurrency: int = 3

    # Bo'sh bazaga birinchi foydalanuvchi. Production'da shu ikkisi
    # (INITIAL_ADMIN_LOGIN / INITIAL_ADMIN_PASSWORD) orqali yaratiladi.
    initial_admin_login: str = ""
    initial_admin_password: str = ""
    # Demo hisoblar (admin/admin123, operator/operator123) — faqat lokal
    # ishlab chiqish va testlar uchun. Ularning paroli ochiq repozitoriyda
    # yozilgan, shuning uchun standart bo'yicha YARATILMAYDI.
    seed_demo_users: bool = False
    # Imzolangan HLS havolalari (app/services/stream_links.py). Bo'sh —
    # imzolanmaydi (lokal ishlab chiqish). Production'da nginx'dagi
    # /etc/nginx/snippets/cam-stream-secret.conf bilan AYNAN bir xil
    # bo'lishi shart — deploy/enable-stream-auth.sh ikkalasini yozadi.
    stream_url_secret: str = ""
    # FastAPI hujjatlari (/docs, /redoc, /openapi.json). Production'da
    # butun API xaritasini internetga ochib qo'ymaslik uchun o'chiq.
    api_docs_enabled: bool = False

    frontend_base_url: str = "http://localhost:5173"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@fjsti.local"
    smtp_use_tls: bool = True

    # ------------------------------------------------------------------
    # Platforma kengaytmasi (2026-09-19)
    # ------------------------------------------------------------------
    # Tashkilot nomi — sarlavhalar, bildirishnomalar va hisobotlarda.
    org_name: str = "Farg'ona JSSTI"
    # Ish kuni shu soatda (institut vaqti) almashadi — kunlik davomat,
    # "bugun" statistikasi va hisobot kunlari (app/timezone.py business_*).
    # 2026-10-06: 6 -> 0 — kalendar kuni. 06:00 da almashganda tunda
    # (00:00-05:59) panel kechagi sanani "Bugun" deb ko'rsatardi; institutda
    # yarim tundan keyin dars/ish yo'q. Frontend: src/lib/uzDate.ts.
    day_start_hour: int = 0
    # Hisobotlar bo'limi paroli (app/routers/report_lock.py): pbkdf2 xesh, .env da.
    # Bo'sh — qulf o'chiq.
    report_password_hash: str = ""
    report_unlock_hours: int = 8
    org_system_name: str = "Situatsion Markaz"

    # Bildirishnomalar (app/services/notifications). Token bo'sh — Telegram
    # o'chiq. Bot @BotFather'da yaratiladi; bot_username bog'lash havolasi
    # (t.me/<bot>?start=<kod>) uchun.
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""
    # Botga yozilgan "/start <kod>" xabarlarini o'qish (getUpdates, leader
    # jarayonida). Webhook ishlatilsa o'chiriladi.
    telegram_polling_enabled: bool = True
    telegram_api_base_url: str = "https://api.telegram.org"
    # SMS: 'eskiz' (eskiz.uz) yoki 'none'.
    sms_provider: Literal["eskiz", "none"] = "none"
    eskiz_email: str = ""
    eskiz_password: str = ""
    eskiz_sender: str = "4546"
    eskiz_base_url: str = "https://notify.eskiz.uz/api"
    # Bir xabarni yuborishga urinishlar orasidagi vaqt va urinishlar soni.
    notification_timeout_seconds: float = 10.0
    notification_log_retention_days: int = 90
    # Ota-onaga xabar: kelganda (birinchi qayd) va kun oxirida kelmaganda.
    parent_notify_arrival_enabled: bool = False
    parent_notify_absence_enabled: bool = False

    # Hodisa ish jarayoni: og'irlik bo'yicha hal qilish muddati (daqiqa).
    # 0 — muddat qo'yilmaydi. Muddati o'tgan hodisa 'event_overdue' qoidasiga
    # ko'ra ogohlantiriladi.
    event_sla_minutes_high: int = 15
    event_sla_minutes_medium: int = 60
    event_sla_minutes_low: int = 240
    event_escalation_interval_seconds: int = 60

    # Prometheus /metrics. Token bo'sh bo'lmasa "Authorization: Bearer <token>"
    # talab qilinadi; bo'sh bo'lsa faqat ichki tarmoqdan (nginx uni tashqariga
    # ochmaydi).
    metrics_enabled: bool = True
    metrics_token: str = ""

    # HEMIS (hemis.uz universitet API). base_url masalan
    # https://student.fjsti.uz/rest — token HEMIS admin panelidan olinadi.
    # iMentor integratsiyasi (app/routers/integration_v1.py): server-server
    # "bu kim?" API — talabani HEMIS ID, JSHSHIR yoki yuz orqali aniqlash.
    # Kalit bo'sh — API o'chiq (har so'rov 401). IP ro'yxati bo'sh — har
    # qanday manzil (kalit baribir shart); "1.2.3.4, 10.0.0.0/8" ko'rinishida.
    camfermi_integration_key: str = ""
    integration_allowed_ips: str = ""
    integration_rate_limit_per_minute: int = 60
    # Yuz bo'yicha aniqlash chegarasi. Kamera davomatidan (0.50) qat'iyroq:
    # iMentor odatda telefon selfisini yuboradi (ro'yxatdan o'tish rasmiga
    # yaqin sharoit), noto'g'ri odamni aytish esa qimmat. margin — eng yaqin
    # nomzod ikkinchisidan shuncha uzoq bo'lishi kerak.
    integration_face_threshold: float = 0.55
    integration_face_margin: float = 0.05
    integration_max_image_bytes: int = 5 * 1024 * 1024
    hemis_base_url: str = ""
    hemis_api_token: str = ""
    # HEMIS'ni BUTUNLAY uzish (2026-10-09, buyurtmachi qarori): ro'yxat
    # tozalangan va qo'lda yuritiladi. Kunlik sinxron o'chirilgan klonlarni
    # (tasdiqlangan egizagi HEMIS ID'siz, ismi boshqacha yozilgan) har kuni
    # qayta yaratardi. False — HEMIS'ga HECH QANDAY so'rov yo'q: sinxron,
    # dars jadvali, davomat, rasmlar, "Hozir sinxronlash" tugmasi va havoladagi
    # HEMIS surati bilan shaxs tekshiruvi. Qayta ulash: HEMIS_ENABLED=true.
    hemis_enabled: bool = False
    # 0 — faqat qo'lda ("Sinxronlash" tugmasi). >0 — har N soatda.
    # HEMIS sozlangan bo'lsagina ishlaydi (hemis_configured). Kuniga bir marta
    # to'liq (talabalar, xodimlar, guruhlar, jadval); jadvalning o'zi tez-tez.
    hemis_sync_interval_hours: int = 24
    hemis_schedule_interval_hours: float = 3.0
    hemis_schedule_days_back: int = 1
    hemis_schedule_days_ahead: int = 14
    hemis_page_size: int = 200
    # Davomat HEMIS'dan (app/jobs/hemis_attendance_sync.py): ish soatlarida har
    # N daqiqada BUGUNGI kun (o'qituvchilar har darsni belgilab boradi),
    # tugash soatidan keyin va ertasi kuni ertalab — yakuniy (darsi jadvalda
    # bo'lib, HEMIS'da o'tkazilmagan o'qituvchi "kelmadi"). Kamera, turniket
    # va qo'lda kiritilgan yozuvlarga tegilmaydi.
    hemis_attendance_sync_enabled: bool = True
    hemis_attendance_interval_minutes: int = 30
    hemis_attendance_start_hour: int = 8
    hemis_attendance_end_hour: int = 19
    # HEMIS rasmidan tanitish (app/jobs/hemis_photos.py): har N soniyada bir
    # to'plam, fon navbatida (davomat kadrlaridan keyin).
    # O'CHIRILGAN (2026-09-26, institut qarori): HEMIS'dagi bitta portret
    # tanish uchun yetarli emas — faqat havola orqali uch tomonlama
    # ro'yxatdan o'tgan yuzlar ishlatiladi.
    hemis_photo_enrollment: bool = False
    # XODIMLAR uchun istisno (2026-10-06, buyurtmachi qarori): 966 xodimdan
    # faqat 18 tasi uch tomonlama ro'yxatdan o'tgan — qolgan 948 tasini
    # kamera umuman tanimasdi. Xodimga bitta HEMIS portreti yetarli
    # (boshqa odamga juda o'xshasa yozilmaydi). Talabalar uchun 26-sentabr
    # qarori o'zgarmaydi. hemis_photo_enrollment o'chiq bo'lsa ham vazifa
    # xodimlar uchun ishlaydi.
    hemis_photo_staff_single: bool = True
    # Nazorat → "Kriteriyalar bo'yicha": Diqqat ustuni foizda. Darsdagi diqqat
    # tahlili (#19) hali ishlamaydi, shuning uchun NAMUNA qiymat: davomati bor
    # har guruhga 65-90% (guruh + sana bo'yicha barqaror). Buyurtmachi
    # so'rovi bilan ko'rsatish uchun (2026-10-06); katak izohida "namuna" deb
    # yoziladi. Haqiqiy tahlil ishga tushganda — False.
    demo_attention_percent: bool = True
    hemis_photo_batch: int = 60
    hemis_photo_interval_seconds: int = 300
    hemis_photo_busy_pause_seconds: int = 5
    # Dublikat qidirish (app/services/person_dedupe.py): yuzi shundan o'xshash
    # va familiya-ismi mos (tartibi boshqa bo'lsa ham) yozuvlar bir odam;
    # ismi boshqa bo'lsa — faqat ko'rib chiqish uchun (birlashtirilmaydi).
    dedupe_face_similarity: float = 0.70
    # Noma'lum yuzlarni yangi baza bilan qayta solishtirish
    # (app/jobs/unknown_rematch.py) — oddiy tanishdan qat'iyroq chegara.
    unknown_rematch_enabled: bool = True
    # Tizim nosozliklari haqida Telegram xabari (app/jobs/system_alerts.py).
    system_alerts_enabled: bool = True
    system_alerts_interval_seconds: int = 300
    system_alerts_repeat_hours: int = 6
    system_alerts_disk_percent: float = 90.0
    system_alerts_hemis_hours: int = 48
    # Fermi Face ID — institut loyihalari uchun yuz orqali kirish
    # (app/services/faceid.py). Chegaralar: 1:1 — ID kiritilganda (odamning
    # o'z yuziga), 1:N — faqat yuz bilan (qat'iyroq va ikkinchi nomzoddan uzoq).
    # Yoqilganda rozilik matniga Face ID maqsadi qo'shiladi (app/services/privacy.py) —
    # shu bilan birga CONSENT_VERSION ni oshiring (v2): eski roziliklar eskirgan
    # deb ko'rsatiladi va odamlar yangi maqsadga qayta rozilik beradi.
    faceid_enabled: bool = False
    faceid_match_threshold: float = 0.50
    faceid_anchor_min: float = 0.40
    faceid_identify_threshold: float = 0.60
    faceid_identify_margin: float = 0.10
    faceid_frame_consistency: float = 0.30
    faceid_challenge_seconds: int = 120
    faceid_code_seconds: int = 120
    faceid_max_failures: int = 5
    faceid_lock_minutes: int = 15
    # O'zi ro'yxatdan o'tgan yuz (JSHSHIR sir emas) — administrator
    # tasdiqlamaguncha Face ID uchun yaroqsiz. None (eski) yuzlar — ishonchli.
    faceid_trust_self_enrolled: bool = False
    faceid_trust_legacy: bool = True
    unknown_rematch_interval_seconds: int = 1800
    unknown_rematch_days: int = 2
    unknown_rematch_similarity: float = 0.55
    unknown_rematch_margin: float = 0.08
    unknown_rematch_min_px: int = 36
    dedupe_face_only_similarity: float = 0.80
    hemis_photo_min_face_px: int = 60
    hemis_photo_retry_minutes: int = 60
    # O'qituvchi darsga kelmadi (app/jobs/teacher_absence.py) — kamerasiz xonadagi
    # darslar uchun: dars boshlanganidan shuncha daqiqa o'tib ham bugun hech bir
    # kamera ko'rmagan bo'lsa, "teacher_absent" bildirishnomasi.
    teacher_absence_alerts: bool = True
    teacher_absence_after_minutes: int = 10
    # HEMIS'da endi yo'q odamni faolsizlantirish (o'chirmaydi).
    hemis_deactivate_missing: bool = False

    # Turniket / kirish nazorati (app/services/integrations/access_control.py).
    access_control_enabled: bool = True
    access_poll_interval_seconds: int = 10

    # PTZ (app/services/ptz.py).
    ptz_timeout_seconds: float = 5.0

    # Maxfiylik va saqlash muddati (app/jobs/cleanup.py).
    # Rozilik matni versiyasi — matn o'zgarsa oshiriladi.
    consent_version: str = "v1"
    # Ochiq ro'yxatdan o'tishda rozilik belgisi majburiy.
    consent_required_for_enrollment: bool = True
    # Faolsizlantirilgan odamning yuz rasmi va embedding'i shuncha kundan
    # keyin o'chiriladi. 0 — o'chirilmaydi.
    biometric_retention_days_after_inactive: int = 30
    # Hodisa snapshotlari (MinIO) — hodisaning o'zidan oldin o'chirilishi
    # mumkin. 0 — event_retention_days bilan birga.
    snapshot_retention_days: int = 90
    access_event_retention_days: int = 365
    # Kameralardagi tashriflar (presence_visits) — shaxs harakati tarixi.
    # 1 yildan eskisi kerak emas va jadval cheksiz o'smasin. 0 — o'chirilmaydi.
    presence_visit_retention_days: int = 365
    # Notanish yuzlar (kesilgan yuz rasmi bilan): qayta moslash 2 kun,
    # takroriylar 14 kun oralig'ida ishlaydi; 90 kundan eskisi o'chiriladi.
    unknown_sighting_retention_days: int = 90

    # ── Kunlik video tahlil (docs/KUNLIK_VIDEO_TAHLIL.md) ──────────────────
    # "kunlik" — kun davomida AI ishlamaydi; kun oxirida NVR yozuvlari
    # tahlil qilinadi (app/jobs/video_analysis.py). "realtime" — eski rejim:
    # kameralar uzluksiz tahlil qilinadi (server yukni ko'tarmagani uchun
    # 2026-10-04 dan standart emas).
    analysis_mode: Literal["kunlik", "realtime"] = "kunlik"
    # Tahlil shu paytda boshlanadi va shu payt kun oynasining oxiri.
    video_analysis_start: str = "20:00"
    # Kun oynasining boshi — kirish kameralari shundan boshlab ko'riladi.
    video_analysis_day_start: str = "07:00"
    # Bir vaqtda nechta vazifa (kamera×oraliq) tahlil qilinadi. Yuz/poza
    # modellarining o'z navbatlari baribir CPU'ni cheklaydi; bu — NVR'dan
    # bir vaqtda o'qiladigan oqimlar va xotira uchun.
    video_analysis_concurrency: int = 6
    # Server o'chib qolgan kunlar shuncha kun orqaga to'ldiriladi.
    video_analysis_catchup_days: int = 2
    video_analysis_poll_seconds: int = 60
    # Bitta vazifa yiqilsa necha marta qayta uriniladi.
    video_analysis_max_attempts: int = 3
    # Kun tahlili "xato" bilan tugasa (agregatsiya yiqildi) shuncha marta
    # avtomatik qayta uriniladi, har safar kamida shuncha daqiqadan keyin.
    # Kuzatuvlar saqlangani uchun video qayta o'qilmaydi — faqat agregatsiya.
    video_analysis_day_retries: int = 2
    video_analysis_retry_minutes: int = 30
    # Kirish/chiqish kameralari: uzluksiz, shuncha kadr/s. Odam eshikdan
    # 2-3 s da o'tadi: tig'iz soatlarda 2 kadr/s, qolgan vaqtda 1 kadr/s
    # (klip ichidagi iz birlashtirish 2-3 kadrdan ham ishonchli tanitadi).
    # Harakatsiz kadrlar baribir tahlil qilinmaydi (app/batch/analyzer.py).
    video_analysis_entrance_fps: float = 1.0
    video_analysis_entrance_peak_fps: float = 2.0
    video_analysis_entrance_peak_windows: str = "07:00-09:30,16:00-19:00"
    # Tahlil shu paytgacha (ertasi kuni, institut soati) tugamasa, qolgan
    # past ustuvor vazifalar (chekish, umumiy) bekor qilinadi va natija
    # bor ma'lumotdan chiqariladi — ertalab hisobot tayyor bo'lsin.
    video_analysis_deadline: str = "08:00"
    # Kirish kameralari oralig'i shuncha daqiqalik bo'laklarga bo'linadi
    # (parallel o'qish va qayta urinish birligi).
    video_analysis_chunk_minutes: int = 30
    # Dars xonasi: boshlanish oynasi (kechikish, #8, #22).
    video_analysis_lesson_start_before_minutes: int = 10
    video_analysis_lesson_start_after_minutes: int = 20
    video_analysis_lesson_start_step_seconds: int = 60
    # Dars o'rtasi: diqqat (#19) va o'qituvchi faolligi (#21).
    video_analysis_lesson_mid_step_minutes: int = 5
    # Dars oxiri: erta ketish (#9).
    video_analysis_lesson_end_minutes: int = 15
    video_analysis_lesson_end_step_seconds: int = 60
    # Bitta klip uzunligi va undagi kadr/s (klipdan 2-3 kadr olinadi:
    # bir yuzni bir necha marta ko'rish — track birlashtirish uchun).
    video_analysis_clip_seconds: float = 3.0
    video_analysis_clip_fps: float = 1.0
    # Boshqa kameralar (koridor, ofis, laboratoriya): har shuncha daqiqada
    # bitta klip — xalat (#10) va "binoda bo'lgan" ko'rinishlari uchun.
    # 0 — bunday kameralar ko'rilmaydi.
    video_analysis_general_step_minutes: int = 10
    # Chekish (#15) — "tashqi"/"koridor" turidagi kameralar: har shuncha
    # daqiqada uzunroq klip (takroriy qo'l-og'iz harakatini ko'rish uchun).
    video_analysis_smoking_step_minutes: int = 5
    video_analysis_smoking_clip_seconds: float = 20.0
    video_analysis_smoking_fps: float = 2.0
    # Tahlil kadrining eng uzun tomoni (4K asosiy oqim kichraytiriladi).
    video_analysis_max_side: int = 1920
    # NVR o'qishining umumiy vaqt chegarasi (bir vazifa, soniya).
    video_analysis_read_timeout_seconds: float = 900.0
    # Kuzatuvlar (har tanilgan yuz) shuncha kun saqlanadi.
    video_observation_retention_days: int = 30
    # Agregatsiya chegaralari.
    video_lesson_min_sightings: int = 2
    video_lesson_early_leave_minutes: int = 10
    # Xalat (#10): kim uchun majburiy (StudentStaff.type, vergul bilan).
    # Xodimlar orasida ma'muriy xodimlar ham bor — ular uchun xalat talab
    # qilinmaydi; o'qituvchilar lavozimi bo'yicha (coat_required_positions).
    coat_required_types: str = "talaba"
    # Shu so'zlardan biri lavozimda bo'lgan xodim ham xalat kiyishi shart.
    coat_required_positions: str = "o'qituvchi,assistent,dotsent,professor,mudir,ordinator,shifokor,hamshira"
    coat_white_fraction: float = 0.42
    coat_dark_fraction: float = 0.15
    coat_min_samples: int = 3
    coat_violation_ratio: float = 0.3
    coat_ok_ratio: float = 0.6
    coat_min_face_px: int = 36
    # Ixtiyoriy: o'qitilgan klassifikator (YOLO-cls, sinflar: oq_xalat /
    # boshqa). Bo'sh — rang qoidasi ishlatiladi.
    coat_model_path: str = ""
    # Chekish (#15).
    smoking_min_episodes: int = 2
    smoking_hand_mouth_ratio: float = 0.55
    # Ixtiyoriy: sigaret/vape sinfi bor YOLO detektor og'irliklari.
    smoking_model_path: str = ""
    smoking_model_confidence: float = 0.35
    # Bir odam/kamera uchun bir kunda ko'pi bilan shuncha chekish hodisasi.
    smoking_max_events_per_camera_day: int = 5
    # Kamera turidan qat'i nazar hamma kriteriyalar hamma kamerada: har
    # kamera kun bo'yi chekish/xalat/tanish kliplari bilan ko'riladi (dars
    # xonasi — darslardan tashqari vaqtda ham). Kamera turlari hali
    # belgilanmagan joyda (yoki sinovda) "ko'ringan har bir odam tekshirilsin".
    video_analysis_everywhere: bool = False
    # Har aniqlangan holat (kech kelish, erta ketish, xalatsizlik, chekish,
    # past diqqat, o'qituvchi...) uchun yozuvdan video dalil: holatdan
    # yarmi oldin, yarmi keyin. Rasm dalili bilan birga — ikkinchi dalil.
    video_evidence_clips: bool = True
    video_evidence_clip_seconds: int = 120
    # Klip balandligi (piksel) — 4K yozuv 720p H.264 ga siqiladi (~5-10 MB).
    video_evidence_clip_height: int = 720
    # Bir kunda ko'pi bilan shuncha klip (bir xil kamera va paytdagi
    # holatlar bitta klipni bo'lishadi) va parallel kesish.
    video_evidence_clips_max: int = 600
    video_evidence_concurrency: int = 3
    # "Kelmadi" faqat ertalabki kelish oynasi (kun boshidan
    # attendance_late_window_end gacha) kliplarining kamida shuncha qismi
    # haqiqatan o'qilgan bo'lsa yoziladi (app/batch/rules.arrival_coverage).
    video_absence_min_coverage: float = 0.8
    # Diqqat va o'qituvchi faolligi shundan past bo'lsa — holat (dalil bilan).
    video_attention_low_score: int = 60
    video_teacher_activity_low_score: int = 40
    # Kunlik tahlil natijasidan hodisalar (xalat, chekish, o'qituvchi) yaratilsinmi.
    video_analysis_events: bool = True
    # Bir kunda ko'pi bilan shuncha "xalat kiyilmagan" hodisasi (qolganlari
    # faqat kunlik natijada) — tekshiruv navbati to'lib ketmasin.
    video_analysis_coat_events_max: int = 300
    # Yozib olingan videolarni import qilish papkasi (scripts/video_tahlil.py):
    # ichida kanal papkalari, "Yuklangan videolar" NVR'i shu yerga qaraydi.
    # Docker'da: /data/nvr-eksport (deploy/docker-compose.ai-worker.yml).
    video_import_dir: str = "nvr-eksport"

settings = Settings()
