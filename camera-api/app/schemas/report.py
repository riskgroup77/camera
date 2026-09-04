from typing import Literal

from app.schemas.base import CamelModel


class ReportStatOut(CamelModel):
    label: str
    value: str


class ReportSectionOut(CamelModel):
    title: str
    rows: list[ReportStatOut]
    note: str | None = None


class ReportOut(CamelModel):
    """Matches src/types/index.ts `Report` exactly."""

    id: str
    period: Literal["Kunlik", "Haftalik", "Oylik"]
    period_label: str
    generated_at: str
    source: Literal["rule", "llm"]
    summary: str
    body: str
    stats: list[ReportStatOut]
    sections: list[ReportSectionOut] = []


class ReportGenerateIn(CamelModel):
    period: Literal["Kunlik", "Haftalik", "Oylik"]
