"""Contrato de salida que FastAPI publica en /docs y /openapi.json."""
from typing import Literal
from pydantic import BaseModel, ConfigDict


Area = Literal["contratos", "personeria_juridica"]


class Health(BaseModel):
    ok: bool
    service: str


class Accepted(BaseModel):
    job_id: str
    status: Literal["queued"]
    files: list[str]


class Source(BaseModel):
    name: str
    start_page: int
    end_page: int


class Stamp(BaseModel):
    bbox: tuple[float, float, float, float]
    text: str
    confidence: float
    requires_review: bool


class Page(BaseModel):
    model_config = ConfigDict(extra="allow")
    page: int
    engine: str
    text: str
    lines: list[str]
    confidence: float | None
    requires_review: bool
    source_id: int | None = None
    source_name: str | None = None
    source_page: int | None = None
    stamps: list[Stamp] | None = None
    warning: str | None = None


class Result(BaseModel):
    area: Area | None = None
    job_id: str
    total_pages: int
    pages: list[Page]
    documents: list[Source]
    protocol: str
    requires_review: bool
    sources: list[Source] | None = None
    protocol_url: str | None = None


class State(BaseModel):
    area: Area | None = None
    status: Literal["queued", "processing", "completed", "failed"]
    files: list[str] = []
    processed_pages: int = 0
    total_pages: int | None = None
    error: str | None = None
    result: Result | None = None


class Exported(Source):
    file: str
    url: str


class Split(BaseModel):
    job_id: str
    documents: list[Exported]


class Cut(BaseModel):
    job_id: str
    file: str
    exported_pages: int
    url: str
