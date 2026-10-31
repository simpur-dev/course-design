from __future__ import annotations

from pydantic import BaseModel, Field


class AuditRequest(BaseModel):
    draft: str = Field(..., min_length=1, max_length=512)
    bib: str = Field(..., min_length=1, max_length=512)
    paragraphs: int = Field(5, ge=1, le=10)
    per_leg: int = Field(20, ge=1, le=100)


class MemoryWriteRequest(BaseModel):
    project: str = Field(..., min_length=1, max_length=120)
    kind: str = Field(..., min_length=1, max_length=32)
    text: str = Field(..., min_length=1, max_length=2000)
    reason: str | None = Field(None, max_length=500)


class MemoryProjectRequest(BaseModel):
    project: str = Field(..., min_length=1, max_length=120)
