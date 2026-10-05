from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.base import CamelModel


class PersonLocationSearchIn(CamelModel):
    query: str = Field(min_length=2, max_length=160)
    limit: int = Field(default=12, ge=1, le=30)


class PersonLocationOut(CamelModel):
    id: str
    full_name: str
    type: Literal["talaba", "xodim"]
    faculty: str | None = None
    group_or_position: str
    initials: str
    camera_id: str | None = None
    camera_name: str | None = None
    building: str | None = None
    floor: int | None = None
    zone: str | None = None
    last_seen_at: datetime | None = None
    currently_visible: bool = False
    has_face: bool = True
    photo_url: str | None = None


class PhotoPersonMatch(CamelModel):
    id: str
    full_name: str
    type: Literal["talaba", "xodim"]
    group_or_position: str
    similarity: float
    photo_url: str | None = None
    last_seen_at: datetime | None = None


class PhotoSightingMatch(CamelModel):
    id: str
    similarity: float
    crop_url: str | None = None
    camera_id: str | None = None
    camera_name: str | None = None
    first_seen_at: datetime
    last_seen_at: datetime
    hits: int


class PhotoSearchOut(CamelModel):
    people: list[PhotoPersonMatch]
    sightings: list[PhotoSightingMatch]
    date_from: str
    date_to: str


class RouteStopOut(CamelModel):
    camera_id: str | None = None
    camera_name: str | None = None
    building: str | None = None
    floor: int | None = None
    zone: str | None = None
    started_at: datetime
    ended_at: datetime
    count: int
    best_similarity: float | None = None


class PersonRouteOut(CamelModel):
    person_id: str
    full_name: str
    day: str
    stops: list[RouteStopOut]
