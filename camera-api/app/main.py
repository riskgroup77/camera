import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

from app.config import settings
from app.database import SessionLocal, engine
from app.jobs.attendance_ai import attendance_ai_loop
from app.jobs.camera_health import camera_health_loop
from app.jobs.cleanup import cleanup_loop
from app.jobs.fire_ai import fire_ai_loop
from app.jobs.leader_lock import release_leadership, try_become_leader
from app.jobs.vision_ai import vision_ai_loop
from app.logging_config import configure_logging
from app.rate_limit import limiter
from app.services import video_gateway
from app.services.stream_cache import shutdown_stream_cache, stream_cache_reaper_loop
from app.storage import check_bucket
from app.routers import (
    ai_modules,
    attendance,
    audit_log,
    auth,
    cameras,
    events,
    face,
    lesson_sessions,
    org_structure,
    public,
    reports,
    students_staff,
    system,
    uploads,
    users,
)
from app.seed import seed_all

configure_logging()
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with SessionLocal() as session:
        await seed_all(session)

    # See app/jobs/leader_lock.py: with WEB_CONCURRENCY>1 (multiple
    # uvicorn worker processes), only one worker should run the AI sweep
    # loops — otherwise every camera gets swept once per worker, per
    # interval, producing duplicate writes. cleanup_loop stays ungated
    # (its deletes are idempotent; redundant runs are harmless).
    is_leader = await try_become_leader()
    tasks = [asyncio.create_task(cleanup_loop())]
    if is_leader:
        tasks += [
            asyncio.create_task(camera_health_loop()),
            asyncio.create_task(attendance_ai_loop()),
            asyncio.create_task(vision_ai_loop()),
            asyncio.create_task(fire_ai_loop()),
            asyncio.create_task(stream_cache_reaper_loop()),
        ]
        logger.info("acquired AI sweep leader lock — sweep loops running in this worker", extra={"event": "leader_elected"})
    else:
        logger.info(
            "another worker already holds the AI sweep leader lock — sweep loops NOT started here",
            extra={"event": "leader_skipped"},
        )

    logger.info("startup complete", extra={"event": "startup"})
    yield
    for task in tasks:
        task.cancel()
    if is_leader:
        await shutdown_stream_cache()
    await release_leadership()
    logger.info("shutting down", extra={"event": "shutdown"})


app = FastAPI(title="Situatsion Markaz API", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.cors_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(students_staff.router)
app.include_router(org_structure.router)
app.include_router(audit_log.router)
app.include_router(cameras.router)
app.include_router(events.router)
app.include_router(uploads.router)
app.include_router(face.router)
app.include_router(ai_modules.router)
app.include_router(attendance.router)
app.include_router(lesson_sessions.router)
app.include_router(reports.router)
app.include_router(system.router)
app.include_router(public.router)


@app.get("/health")
async def health(response: Response) -> dict[str, str]:
    """Real readiness check — verifies every external dependency the API
    actually needs to serve traffic (database, MinIO/S3 storage, MediaMTX
    video gateway), not just that the process is running. Kubernetes/
    load-balancer health checks should hit this. A single failed
    dependency degrades the whole response — a half-broken deployment
    (e.g. DB fine but storage down) should not read as healthy."""
    checks: dict[str, str] = {}

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        logger.error("health check: database unreachable", extra={"error": str(exc)})
        checks["database"] = "unreachable"

    try:
        await asyncio.to_thread(check_bucket)
        checks["storage"] = "ok"
    except Exception as exc:
        logger.error("health check: storage (MinIO) unreachable", extra={"error": str(exc)})
        checks["storage"] = "unreachable"

    try:
        await video_gateway.check_reachable()
        checks["video_gateway"] = "ok"
    except Exception as exc:
        logger.error("health check: video gateway (MediaMTX) unreachable", extra={"error": str(exc)})
        checks["video_gateway"] = "unreachable"

    if any(v != "ok" for v in checks.values()):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", **checks}
    return {"status": "ok", **checks}
