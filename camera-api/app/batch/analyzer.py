"""Bitta vazifani (kamera × kliplar) tahlil qilish.

Har klip uchun:
  1. NVR'dan kadrlar (vaqti bilan) oqim sifatida o'qiladi;
  2. har kadrda yuzlar aniqlanadi (InsightFace), klip ichida izlarga
     bog'lanadi (app/batch/tracking.py) — iz tugaganda birlashtirilgan
     vektor ro'yxat bilan solishtiriladi;
  3. maqsadga qarab qo'shimcha signallar: telefon (diqqat #19), tana
     sohasining rangi (xalat #10), o'qituvchi pozasi (faollik #21), butun
     klip pozalari (chekish #15).
Natija — tanilgan odamlar bo'yicha kuzatuvlar va vazifa xulosasi; bazaga
yozish orkestratorda (app/jobs/video_analysis.py).
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date as date_type, datetime

import cv2
import numpy as np

from app.batch import coat as coat_rules
from app.batch.planner import P_ACTIVITY, P_ATTENTION, P_COAT, P_IDENTITY, P_SMOKING, Clip
from app.batch.smoking import PoseFrame, cigarette_boxes, detect_smoking, movement_score
from app.batch.tracking import FaceSample, Track, TrackBuilder
from app.config import settings
from app.services.face_matching import CandidateMatrix
from app.services.nvr.sources import Frame, PlaybackSource, VideoReadError

logger = logging.getLogger("app.batch.analyzer")

PERSON_CLASS = 0
PHONE_CLASS = 67
CUP_BOTTLE_CLASSES = (39, 41)
# Izdagi bog'lanish oralig'i: klip ichidagi kadrlar 0,5-1 s, kirish
# kamerasida odam bir lahza ko'rinmay qolishi mumkin.
TRACK_GAP_SECONDS = 2.5
# Bir izda xalat ko'pi bilan shuncha kadrda baholanadi (YOLO odam ramkasi qimmat).
COAT_SAMPLES_PER_TRACK = 3
# Uzun (kirish) klipda harakatsiz kadr tahlil qilinmaydi, lekin kamida shu
# oraliqda bittasi tahlil qilinadi.
MOTION_FORCE_SECONDS = 10.0
LONG_CLIP_SECONDS = 120.0
# Chekish klipida poza har kadrda kerak, yuz esa faqat kimligini bilish
# uchun — har shuncha kadrda bittasida aniqlanadi (CPU tejaladi).
SMOKING_FACE_STRIDE = 4


@dataclass
class ObservationData:
    person_id: str
    seen_at: datetime
    last_seen_at: datetime
    similarity: float
    margin: float
    frames: int
    face_px: int
    frontal_frames: int = 0
    phone_frames: int = 0
    coat_frames: int = 0
    coat_white_frames: int = 0
    coat_fraction: float | None = None
    movement: float | None = None
    evidence_key: str | None = None
    clip_index: int = 0


@dataclass
class JobOutcome:
    frames: int = 0
    faces: int = 0
    observations: list[ObservationData] = field(default_factory=list)
    # [klip indeksi, o'qilgan kadrlar, ko'rilgan yuzlar]
    covered: list[list[int]] = field(default_factory=list)
    smoking: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def result_json(self) -> dict:
        return {"smoking": self.smoking, "errors": self.errors[-5:]}


@dataclass
class JobContext:
    job_id: uuid.UUID
    day: date_type
    camera_id: uuid.UUID
    camera_name: str
    clips: list[Clip]
    candidates: CandidateMatrix
    teacher_id: str | None = None
    # (kun, odam) — xalat dalili shu kun allaqachon saqlanganlar (bitta yetadi).
    evidence_registry: set | None = None


def _decode(jpeg: bytes) -> np.ndarray | None:
    try:
        return cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    except cv2.error:
        return None


def _thumbnail(jpeg: bytes) -> np.ndarray | None:
    try:
        image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_REDUCED_GRAYSCALE_8)
    except cv2.error:
        return None
    if image is None:
        return None
    return cv2.resize(image, (64, 36)).astype(np.float32)


def _moved(thumb: np.ndarray, previous: np.ndarray) -> bool:
    """Kichraytirilgan kadrlarda o'zgargan piksellar ulushi (uzoqdagi kichik
    odam o'rtacha farqni deyarli o'zgartirmaydi — shuning uchun ulush)."""
    changed = np.abs(thumb - previous) > settings.motion_gate_pixel_delta
    return float(changed.mean()) >= settings.motion_gate_min_changed_fraction


def _face_px(bbox) -> int:
    return int(max(0.0, float(bbox[3]) - float(bbox[1])))


def _quality(face) -> float:
    det = float(getattr(face, "det_score", None) or 0.6)
    size = min(1.0, _face_px(face.bbox) / 80.0)
    yaw = getattr(face, "yaw", None)
    turn = 1.0 - min(abs(float(yaw)), 0.6) if yaw is not None else 0.8
    return det * (0.3 + 0.7 * size) * turn


def _frontal(face) -> bool | None:
    landmarks = getattr(face, "landmarks_68", None)
    if landmarks is None:
        yaw = getattr(face, "yaw", None)
        return None if yaw is None else abs(float(yaw)) < 0.2
    from app.services.sleep_detection import is_plausible_frontal

    try:
        return bool(is_plausible_frontal(landmarks))
    except Exception:  # noqa: BLE001
        return None


def phone_near(face_bbox, phones: list) -> bool:
    """Telefon shu talabaning qo'lidami: yuzning ostida/yonida, yelkalar
    kengligida. Butun sinfdagi bitta telefon hammaning ballini tushirmaydi."""
    x1, y1, x2, y2 = (float(v) for v in face_bbox[:4])
    width, height = x2 - x1, y2 - y1
    left, right = x1 - 1.5 * width, x2 + 1.5 * width
    top, bottom = y1 - 0.5 * height, y2 + 4.0 * height
    for phone in phones:
        px1, py1, px2, py2 = (float(v) for v in phone.bbox[:4])
        cx, cy = (px1 + px2) / 2, (py1 + py2) / 2
        if left <= cx <= right and top <= cy <= bottom:
            return True
    return False


def person_box_for(face_bbox, persons: list):
    """Yuz markazini o'z ichiga olgan eng kichik odam ramkasi."""
    x1, y1, x2, y2 = (float(v) for v in face_bbox[:4])
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    best, best_area = None, None
    for person in persons:
        px1, py1, px2, py2 = (float(v) for v in person.bbox[:4])
        if px1 <= cx <= px2 and py1 <= cy <= py2:
            area = (px2 - px1) * (py2 - py1)
            if best_area is None or area < best_area:
                best, best_area = person.bbox, area
    return best


# ── maxsus sigaret modeli (ixtiyoriy) ────────────────────────────────────
_smoking_lock = threading.Lock()
_smoking_state: dict[str, object] = {}


def _smoking_model():
    path = settings.smoking_model_path.strip()
    if not path:
        return None
    with _smoking_lock:
        if _smoking_state.get("path") != path:
            try:
                from ultralytics import YOLO

                _smoking_state["model"] = YOLO(path)
            except Exception:  # noqa: BLE001
                logger.exception("smoking model could not be loaded", extra={"path": path})
                _smoking_state["model"] = None
            _smoking_state["path"] = path
        return _smoking_state["model"]


def _smoking_detect_sync(jpeg: bytes) -> list:
    from app.services.object_detection import DetectedObject

    model = _smoking_model()
    image = _decode(jpeg)
    if model is None or image is None:
        return []
    try:
        results = model.predict(image, conf=settings.smoking_model_confidence, verbose=False)
    except Exception:  # noqa: BLE001
        logger.exception("smoking model failed")
        return []
    out = []
    for result in results:
        for box in result.boxes:
            cls_id = int(box.cls[0])
            out.append(
                DetectedObject(
                    class_id=cls_id,
                    class_name=str(result.names.get(cls_id, cls_id)),
                    confidence=float(box.conf[0]),
                    bbox=tuple(float(v) for v in box.xyxy[0]),
                )
            )
    return out


class Analyzer:
    """Tashqi modellar shu yerda chaqiriladi — testlar ularni almashtiradi."""

    async def faces(self, jpeg: bytes) -> list:
        from app.services.face_recognition import detect_faces
        from app.services.inference_gate import PRIORITY_BACKGROUND

        return await detect_faces(jpeg, priority=PRIORITY_BACKGROUND)

    async def objects(self, jpeg: bytes, class_ids: list[int]) -> list:
        from app.services.object_detection import detect_objects

        return await detect_objects(jpeg, class_ids=class_ids, confidence=0.35)

    async def poses(self, jpeg: bytes) -> list:
        from app.services.pose_detection import detect_poses

        return await detect_poses(jpeg)

    async def cigarettes(self, jpeg: bytes) -> list:
        if not settings.smoking_model_path.strip():
            return []
        return cigarette_boxes(await asyncio.to_thread(_smoking_detect_sync, jpeg))

    async def upload(self, data: bytes, name: str) -> str | None:
        from app.storage import upload_file

        try:
            _file_id, key = await asyncio.to_thread(upload_file, data, name, "image/jpeg", "video-tahlil")
            return key
        except Exception:  # noqa: BLE001 — dalil saqlanmasa ham natija qoladi
            logger.exception("evidence upload failed")
            return None

    # ── vazifa ──────────────────────────────────────────────────────────

    async def run(
        self, ctx: JobContext, source: PlaybackSource, *, should_stop: Callable[[], bool] | None = None
    ) -> JobOutcome:
        outcome = JobOutcome()
        available = None
        if ctx.clips:
            available = await source.available(
                min(c.start for c in ctx.clips), max(c.end for c in ctx.clips)
            )
        coat_evidence: dict[str, tuple[int, bytes]] = {}
        for index, clip in enumerate(ctx.clips):
            if should_stop is not None and should_stop():
                break
            if available is not None and not any(
                span.start < clip.end and span.end > clip.start for span in available
            ):
                continue  # NVR'da bu oraliqda yozuv yo'q — qamrovga kirmaydi
            try:
                frames, faces = await self._clip(ctx, index, clip, source, outcome, coat_evidence, should_stop)
            except VideoReadError as exc:
                outcome.errors.append(str(exc)[:300])
                continue
            if frames:
                outcome.covered.append([index, frames, faces])
        await self._store_coat_evidence(ctx, outcome, coat_evidence)
        return outcome

    async def _clip(
        self,
        ctx: JobContext,
        index: int,
        clip: Clip,
        source: PlaybackSource,
        outcome: JobOutcome,
        coat_evidence: dict[str, tuple[int, bytes]],
        should_stop,
    ) -> tuple[int, int]:
        purposes = set(clip.purposes)
        long_clip = (clip.end - clip.start).total_seconds() > LONG_CLIP_SECONDS
        keep_frames = bool(purposes & {P_ACTIVITY, P_SMOKING}) and not long_clip
        face_stride = SMOKING_FACE_STRIDE if P_SMOKING in purposes else 1
        builder = TrackBuilder(TRACK_GAP_SECONDS)
        kept: list[Frame] = []
        track_frames: dict[int, list] = {}  # frame_index -> faces (smoking bog'lash uchun)
        frames_read = 0
        faces_seen = 0
        last_thumb: np.ndarray | None = None
        last_analyzed_at: datetime | None = None
        frame_index = -1
        finished_tracks: list[Track] = []

        async for frame in source.clip(
            clip.start,
            clip.end,
            clip.fps,
            max_side=settings.video_analysis_max_side,
            timeout=settings.video_analysis_read_timeout_seconds,
            should_stop=should_stop,
        ):
            frame_index += 1
            frames_read += 1
            outcome.frames += 1
            if keep_frames:
                kept.append(frame)
            if long_clip:
                thumb = await asyncio.to_thread(_thumbnail, frame.jpeg)
                if (
                    thumb is not None
                    and last_thumb is not None
                    and not builder.active
                    and last_analyzed_at is not None
                    and (frame.at - last_analyzed_at).total_seconds() < MOTION_FORCE_SECONDS
                    and not _moved(thumb, last_thumb)
                ):
                    continue  # bo'sh, harakatsiz kadr
                last_thumb = thumb
                last_analyzed_at = frame.at
            if frame_index % face_stride:
                continue
            faces = await self.faces(frame.jpeg)
            if not faces:
                finished_tracks += builder.add(frame.at, [])
                continue
            faces_seen += len(faces)
            outcome.faces += len(faces)
            samples = [
                FaceSample(
                    at=frame.at,
                    frame_index=frame_index,
                    bbox=tuple(float(v) for v in face.bbox[:4]),
                    embedding=getattr(face, "embedding", None),
                    quality=_quality(face),
                    face_px=_face_px(face.bbox),
                    frontal=_frontal(face) if P_ATTENTION in purposes else None,
                )
                for face in faces
            ]
            finished_tracks += builder.add(frame.at, samples)
            if keep_frames:
                track_frames[frame_index] = samples
            await self._frame_signals(frame, samples, builder, purposes, coat_evidence)
            if long_clip and len(finished_tracks) >= 20:
                self._finalize(ctx, index, finished_tracks, outcome)
                finished_tracks = []

        finished_tracks += builder.flush()
        observations = self._finalize(ctx, index, finished_tracks, outcome)
        if P_ACTIVITY in purposes and ctx.teacher_id and kept:
            await self._teacher_activity(ctx, observations, finished_tracks, kept)
        if P_SMOKING in purposes and len(kept) >= 6:
            await self._smoking(ctx, clip, kept, finished_tracks, observations, outcome)
        return frames_read, faces_seen

    async def _frame_signals(self, frame: Frame, samples: list[FaceSample], builder: TrackBuilder, purposes, coat_evidence) -> None:
        want_coat = P_COAT in purposes
        want_phone = P_ATTENTION in purposes
        coat_samples: list[FaceSample] = []
        if want_coat:
            for sample in samples:
                if sample.face_px < settings.coat_min_face_px or sample.embedding is None:
                    continue
                track = next((t for t in builder.active if t.samples and t.samples[-1] is sample), None)
                judged = sum(1 for s in track.samples if s.coat_fraction is not None) if track else 0
                if judged < COAT_SAMPLES_PER_TRACK:
                    coat_samples.append(sample)
        if not coat_samples and not want_phone:
            return
        classes: list[int] = []
        if coat_samples:
            classes.append(PERSON_CLASS)
        if want_phone:
            classes.append(PHONE_CLASS)
        detections = await self.objects(frame.jpeg, classes)
        if want_phone:
            phones = [d for d in detections if d.class_id == PHONE_CLASS]
            for sample in samples:
                sample.phone = phone_near(sample.bbox, phones)
        if coat_samples:
            persons = [d for d in detections if d.class_id == PERSON_CLASS]
            image = await asyncio.to_thread(_decode, frame.jpeg)
            if image is None:
                return
            context = await asyncio.to_thread(coat_rules.frame_context, image)
            for sample in coat_samples:
                result = await asyncio.to_thread(
                    coat_rules.evaluate, image, sample.bbox, person_box_for(sample.bbox, persons), context
                )
                if result is None:
                    continue
                sample.coat_fraction = result.fraction
                sample.coat = result.is_white
                if result.is_white is False:
                    # Dalil uchun kesim — keyin odam aniqlangach saqlanadi.
                    sample_key = id(sample)
                    previous = coat_evidence.get(str(sample_key))
                    if previous is None or previous[0] < sample.face_px:
                        crop = _evidence_crop(image, sample.bbox)
                        if crop is not None:
                            coat_evidence[str(sample_key)] = (sample.face_px, crop)

    def _finalize(self, ctx: JobContext, clip_index: int, tracks: list[Track], outcome: JobOutcome) -> list[tuple[Track, ObservationData]]:
        candidates = ctx.candidates
        usable = [(track, track.fused_embedding()) for track in tracks]
        usable = [(track, vector) for track, vector in usable if vector is not None]
        if not usable or candidates.is_empty:
            return []
        # Iz ikki odamni aralashtirib yubormaganmi: har kadr birlashtirilgan
        # vektorga yetarlicha o'xshash bo'lishi kerak (None — vektor bitta).
        consistency_ok = []
        for track, vector in usable:
            consistency = track.self_consistency()
            if consistency is None or consistency >= 0.30:
                consistency_ok.append((track, vector))
        if not consistency_ok:
            return []
        matches = candidates.graded_matches(
            np.stack([vector for _track, vector in consistency_ok]),
            strict_threshold=settings.attendance_ai_match_threshold,
            relaxed_threshold=settings.attendance_ai_relaxed_threshold,
            margin=settings.attendance_ai_relaxed_margin,
            strict_margin=settings.attendance_ai_strict_margin,
        )
        accepted: list[tuple[Track, ObservationData]] = []
        for (track, _vector), match in zip(consistency_ok, matches, strict=True):
            if match.person_id is None:
                continue
            # Diqqat namunasi: telefon bo'lsa — chalg'igan (yuz yo'nalishidan qat'i nazar).
            frontal = sum(1 for s in track.samples if s.frontal and not s.phone)
            phone = sum(1 for s in track.samples if s.phone)
            coat_judged = [s for s in track.samples if s.coat is not None]
            coat_fractions = [s.coat_fraction for s in track.samples if s.coat_fraction is not None]
            observation = ObservationData(
                person_id=str(match.person_id),
                seen_at=track.first_at,
                last_seen_at=track.last_at,
                similarity=round(float(match.similarity), 4),
                margin=round(float(match.similarity - max(match.second_similarity, 0.0)), 4)
                if match.second_similarity >= 0
                else round(float(match.similarity), 4),
                frames=min(len(track.samples), 32000),
                face_px=min(track.face_px, 32000),
                frontal_frames=frontal,
                phone_frames=phone,
                coat_frames=len(coat_judged),
                coat_white_frames=sum(1 for s in coat_judged if s.coat),
                coat_fraction=round(float(np.mean(coat_fractions)), 3) if coat_fractions else None,
                clip_index=clip_index,
            )
            accepted.append((track, observation))
        # Bir odam bir paytda ikki joyda bo'lmaydi: vaqt bo'yicha kesishgan
        # ikki iz bir odamga moslansa — kuchsizrog'i tashlanadi.
        accepted.sort(key=lambda item: -item[1].similarity)
        kept: list[tuple[Track, ObservationData]] = []
        for track, observation in accepted:
            clash = any(
                other.person_id == observation.person_id
                and other.seen_at <= observation.last_seen_at
                and observation.seen_at <= other.last_seen_at
                for _t, other in kept
            )
            if not clash:
                kept.append((track, observation))
        for track, observation in kept:
            observation._track_ref = track  # type: ignore[attr-defined] — dalil bog'lash uchun
            outcome.observations.append(observation)
        return kept

    async def _teacher_activity(
        self, ctx: JobContext, observations: list[tuple[Track, ObservationData]], _tracks, kept: list[Frame]
    ) -> None:
        for track, observation in observations:
            if observation.person_id != ctx.teacher_id or len(track.samples) < 2:
                continue
            first, last = track.samples[0], track.samples[-1]
            if first.frame_index >= len(kept) or last.frame_index >= len(kept):
                continue
            frame_a, frame_b = kept[first.frame_index], kept[last.frame_index]
            # Poza modeli kadrdagi bir necha (pose_detection_max_poses) odamni
            # qaytaradi — 30 talabali sinfda o'qituvchi ular orasida
            # bo'lmasligi mumkin. Shuning uchun ikkala kadrdan o'qituvchi
            # atrofidagi BIR XIL soha kesiladi va poza o'sha kesimda topiladi.
            crops = await asyncio.to_thread(_teacher_crops, frame_a.jpeg, frame_b.jpeg, first.bbox, last.bbox)
            if crops is None:
                continue
            crop_a, crop_b, size, face_a, face_b = crops
            pose_a = _pose_near(await self.poses(crop_a), face_a, size)
            pose_b = _pose_near(await self.poses(crop_b), face_b, size)
            if pose_a is None or pose_b is None:
                continue
            score = movement_score(pose_a, pose_b, size)
            if score is not None:
                observation.movement = round(score, 1)

    async def _smoking(
        self,
        ctx: JobContext,
        clip: Clip,
        kept: list[Frame],
        _tracks,
        observations: list[tuple[Track, ObservationData]],
        outcome: JobOutcome,
    ) -> None:
        probe = [kept[0], kept[len(kept) // 2], kept[-1]]
        people = 0
        for frame in probe:
            people += len(await self.objects(frame.jpeg, [PERSON_CLASS]))
        if people == 0:
            return
        size = _jpeg_size(kept[0].jpeg)
        if size is None:
            return
        pose_frames = [PoseFrame(at=frame.at, poses=await self.poses(frame.jpeg), size=size) for frame in kept]
        candidates = detect_smoking(pose_frames, clip.fps)
        if not candidates:
            return
        # Nomzod bor — endi istisno obyektlar (telefon, stakan) va sigaret modeli.
        for frame, pose_frame in zip(kept, pose_frames, strict=True):
            pose_frame.objects = await self.objects(frame.jpeg, [PHONE_CLASS, *CUP_BOTTLE_CLASSES])
            pose_frame.cigarettes = await self.cigarettes(frame.jpeg)
        candidates = detect_smoking(pose_frames, clip.fps)
        for candidate in candidates:
            person_id = _person_at(observations, candidate.frame_index, candidate.head_box)
            frame = kept[candidate.frame_index]
            snapshot = await asyncio.to_thread(_annotate, frame.jpeg, candidate.head_box)
            key = await self.upload(snapshot or frame.jpeg, "chekish.jpg")
            outcome.smoking.append(
                {
                    "at": candidate.at.isoformat(),
                    "person_id": person_id,
                    "episodes": candidate.episodes,
                    "confidence": candidate.confidence,
                    "cigarette_seen": candidate.cigarette_seen,
                    "snapshot_key": key,
                }
            )

    async def _store_coat_evidence(self, ctx: JobContext, outcome: JobOutcome, coat_evidence) -> None:
        if not coat_evidence:
            return
        registry = ctx.evidence_registry if ctx.evidence_registry is not None else set()
        best: dict[str, tuple[int, bytes, ObservationData]] = {}
        for observation in outcome.observations:
            track = getattr(observation, "_track_ref", None)
            if track is None or observation.coat_white_frames * 2 >= max(1, observation.coat_frames):
                continue
            for sample in track.samples:
                item = coat_evidence.get(str(id(sample)))
                if item is None:
                    continue
                current = best.get(observation.person_id)
                if current is None or current[0] < item[0]:
                    best[observation.person_id] = (item[0], item[1], observation)
        for person_id, (_px, crop, observation) in best.items():
            key = (ctx.day, person_id)
            if key in registry:
                continue
            stored = await self.upload(crop, "xalat.jpg")
            if stored:
                registry.add(key)
                observation.evidence_key = stored


def _evidence_crop(image: np.ndarray, face_bbox) -> bytes | None:
    height, width = image.shape[:2]
    x1, y1, x2, y2 = (float(v) for v in face_bbox[:4])
    fw, fh = x2 - x1, y2 - y1
    left, top = int(max(0, x1 - 1.6 * fw)), int(max(0, y1 - 0.6 * fh))
    right, bottom = int(min(width, x2 + 1.6 * fw)), int(min(height, y2 + 3.2 * fh))
    if right - left < 8 or bottom - top < 8:
        return None
    ok, buffer = cv2.imencode(".jpg", image[top:bottom, left:right], [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buffer.tobytes() if ok else None


def _annotate(jpeg: bytes, box) -> bytes | None:
    image = _decode(jpeg)
    if image is None:
        return None
    x1, y1, x2, y2 = (int(v) for v in box)
    cv2.rectangle(image, (x1, y1), (x2, y2), (0, 0, 255), 2)
    ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buffer.tobytes() if ok else None


def _teacher_crops(jpeg_a: bytes, jpeg_b: bytes, box_a, box_b):
    """Ikkala kadrdan bir xil soha: ikki yuz ramkasining birlashmasi atrofida
    eni 6, bo'yi 9 yuz o'lchami (bosh, yelka, qo'llar). Qaytaradi —
    (kesim_a, kesim_b, (eni, bo'yi), yuz_a, yuz_b) kesim koordinatalarida."""
    image_a, image_b = _decode(jpeg_a), _decode(jpeg_b)
    if image_a is None or image_b is None or image_a.shape != image_b.shape:
        return None
    height, width = image_a.shape[:2]
    x1 = min(float(box_a[0]), float(box_b[0]))
    y1 = min(float(box_a[1]), float(box_b[1]))
    x2 = max(float(box_a[2]), float(box_b[2]))
    y2 = max(float(box_a[3]), float(box_b[3]))
    face = max(float(box_a[3]) - float(box_a[1]), float(box_b[3]) - float(box_b[1]), 1.0)
    left, right = int(max(0, x1 - 2.5 * face)), int(min(width, x2 + 2.5 * face))
    top, bottom = int(max(0, y1 - 1.0 * face)), int(min(height, y2 + 7.0 * face))
    if right - left < 16 or bottom - top < 16:
        return None
    out = []
    for image in (image_a, image_b):
        ok, buffer = cv2.imencode(".jpg", image[top:bottom, left:right], [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            return None
        out.append(buffer.tobytes())

    def shift(box):
        return (float(box[0]) - left, float(box[1]) - top, float(box[2]) - left, float(box[3]) - top)

    return out[0], out[1], (right - left, bottom - top), shift(box_a), shift(box_b)


def _jpeg_size(jpeg: bytes) -> tuple[int, int] | None:
    from app.services.image_size import jpeg_dimensions

    return jpeg_dimensions(jpeg)


def _pose_near(poses: list, face_bbox, size: tuple[int, int]):
    if not poses:
        return None
    x1, y1, x2, y2 = (float(v) for v in face_bbox[:4])
    cx, cy = (x1 + x2) / 2 / size[0], (y1 + y2) / 2 / size[1]
    best, best_distance = None, None
    for pose in poses:
        nose = pose.points[0]
        distance = float(np.hypot(nose[0] - cx, nose[1] - cy))
        if best_distance is None or distance < best_distance:
            best, best_distance = pose, distance
    # Burun yuz markazidan yuz kengligining 1,5 baravaridan uzoq — boshqa odam.
    if best_distance is not None and best_distance > 1.5 * (x2 - x1) / size[0] + 0.02:
        return None
    return best


def _person_at(observations: list[tuple[Track, ObservationData]], frame_index: int, head_box) -> str | None:
    hx1, hy1, hx2, hy2 = head_box
    margin_x, margin_y = (hx2 - hx1) * 0.5, (hy2 - hy1) * 0.5
    for track, observation in observations:
        for sample in track.samples:
            if abs(sample.frame_index - frame_index) > SMOKING_FACE_STRIDE:
                continue
            x1, y1, x2, y2 = sample.bbox
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            if hx1 - margin_x <= cx <= hx2 + margin_x and hy1 - margin_y <= cy <= hy2 + margin_y:
                return observation.person_id
    return None
