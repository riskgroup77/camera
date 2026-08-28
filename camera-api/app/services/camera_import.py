"""Bulk camera import from a SADP (Hikvision device-discovery tool) CSV
export — POST /api/cameras/import.

Expected columns (SADP's own export header, matched case/space-insensitively
via _normalize_header): Device Type, Status, IPv4 Address, Device Serial
Number, MAC Address. Everything else SADP exports (ports, firmware, IPv6,
DHCP flags...) is ignored.

SADP only knows network-discovery facts — it has no idea which building or
room a camera physically sits in, and no RTSP credentials. Imported rows
land with zone="Tasniflanmagan" (unclassified), building unset, and
status="nofaol" (not yet live) — an admin reviews and assigns each one via
the normal camera edit form before it's swept by any AI module.

Dedup key is `mac_address`, not `ip` — SADP exports come from cameras that
may get a new IP the next time this same CSV is re-imported (DHCP, or an
admin manually reassigning by hand via SADP's own "Modify Network
Parameters" panel), but the MAC address is the one thing that stays
constant for a given physical device. Devices already known by IP but with
no mac_address on file (hand-added before this feature existed) are also
matched, so re-importing doesn't create a duplicate for a camera someone
already entered manually.
"""

import csv
import io
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Camera
from app.schemas.camera_import import CameraImportErrorOut, CameraImportResultOut

logger = logging.getLogger("app.camera_import")

_REQUIRED_COLUMNS = {"device_type", "status", "ipv4_address", "mac_address"}

# Hikvision NVR/DVR model-number prefixes — these show up in a SADP scan
# alongside the cameras they record from, but a recorder isn't itself a
# camera to add as a video source. Conservative on purpose: only skips
# names that clearly match a known recorder series, never a real IPC.
_RECORDER_PREFIXES = ("DS-77", "DS-78", "DS-79", "DS-96", "DS-98")


def _normalize_header(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


def _looks_like_recorder(device_type: str) -> bool:
    upper = device_type.upper()
    return upper.startswith(_RECORDER_PREFIXES) or "NVR" in upper or "DVR" in upper


def _normalize_mac(mac: str) -> str:
    return mac.strip().lower()


async def _load_existing_mac_addresses(db: AsyncSession) -> set[str]:
    result = await db.execute(select(Camera.mac_address).where(Camera.mac_address.is_not(None)))
    return {_normalize_mac(mac) for (mac,) in result.all() if mac}


async def import_cameras_csv(db: AsyncSession, raw: bytes) -> CameraImportResultOut:
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return CameraImportResultOut(
            imported=0, skipped=0, skipped_recorders=0, errors=[CameraImportErrorOut(row=0, message="CSV bo'sh")]
        )

    field_map = {_normalize_header(h): h for h in reader.fieldnames}
    missing = _REQUIRED_COLUMNS - set(field_map)
    if missing:
        return CameraImportResultOut(
            imported=0,
            skipped=0,
            skipped_recorders=0,
            errors=[CameraImportErrorOut(row=0, message=f"Yetishmayotgan ustunlar: {', '.join(sorted(missing))}")],
        )

    existing_macs = await _load_existing_mac_addresses(db)
    pending_macs: set[str] = set()

    imported = 0
    skipped = 0
    skipped_recorders = 0
    errors: list[CameraImportErrorOut] = []

    for row_num, row in enumerate(reader, start=2):
        device_type = (row.get(field_map["device_type"]) or "").strip()
        status_value = (row.get(field_map["status"]) or "").strip().lower()
        ip = (row.get(field_map["ipv4_address"]) or "").strip()
        mac = (row.get(field_map["mac_address"]) or "").strip()

        if not ip:
            errors.append(CameraImportErrorOut(row=row_num, message="IPv4 Address bo'sh"))
            continue
        if not mac:
            errors.append(CameraImportErrorOut(row=row_num, message="MAC Address bo'sh"))
            continue
        if status_value != "active":
            skipped += 1
            continue
        if _looks_like_recorder(device_type):
            skipped_recorders += 1
            continue

        mac_key = _normalize_mac(mac)
        if mac_key in existing_macs or mac_key in pending_macs:
            skipped += 1
            continue

        db.add(
            Camera(
                name=f"{device_type} ({ip})" if device_type else ip,
                ip=ip,
                port=554,
                zone="Tasniflanmagan",
                resolution="Noma'lum",
                status="nofaol",
                mac_address=mac,
            )
        )
        pending_macs.add(mac_key)
        imported += 1

    return CameraImportResultOut(imported=imported, skipped=skipped, skipped_recorders=skipped_recorders, errors=errors)
