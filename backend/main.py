from __future__ import annotations

import os
import re
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Semaphore

import pymupdf as fitz
import schemas
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from services.document_service import IMAGE_EXT, prepare_pdf
from services.export_service import export, parse_ranges
from services.page_service import read_page
from services.protocol_service import build_protocol, save_protocol
from services.segmentation_service import suggest_segments
from utils.storage import read_json, write_json

BASE = Path(__file__).resolve().parent
DATA = Path(os.getenv("NOTARIA_DATA", BASE / "data" / "jobs")).resolve()
ALLOWED = IMAGE_EXT | {".pdf", ".doc", ".docx"}
worker = Semaphore(1)


@asynccontextmanager
async def lifespan(app):
    DATA.mkdir(parents=True, exist_ok=True)
    for path in DATA.glob("*/state.json"):
        state = read_json(path)
        if state["status"] in {"queued", "processing"}:
            state.update(status="failed", error="Procesamiento interrumpido. Vuelva a enviar los archivos.")
            write_json(path, state)
    yield


app = FastAPI(title="Sistema Notarial MVP", version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("NOTARIA_ORIGINS", "*").split(","),
                   allow_credentials=False, allow_methods=["*"], allow_headers=["*"])


class Segment(BaseModel):
    name: str | None = None
    start_page: int
    end_page: int


class SplitRequest(BaseModel):
    job_id: str
    documents: list[Segment] = Field(min_length=1, max_length=500)


class CutRequest(BaseModel):
    job_id: str
    pages: str = Field(max_length=5000)


def locate(job_id):
    if not re.fullmatch("[0-9a-f]{32}", job_id):
        raise HTTPException(404, "Trabajo no encontrado")
    folder = DATA / job_id
    if (folder / "state.json").is_file():
        return folder, read_json(folder / "state.json")
    # Resultados ya producidos por la primera versión del proyecto.
    if (folder / "result.json").is_file():
        payload = read_json(folder / "result.json")
        return folder, dict(status="completed", processed_pages=payload["total_pages"],
                            total_pages=payload["total_pages"], files=[])
    raise HTTPException(404, "Trabajo no encontrado")


def completed(job_id):
    folder, state = locate(job_id)
    if state["status"] != "completed":
        raise HTTPException(409, state.get("error") or "El trabajo todavía no terminó")
    return folder, state


def process_job(job_id):
    folder, state = locate(job_id)
    with worker:
        try:
            state["status"] = "processing"
            write_json(folder / "state.json", state)
            path = prepare_pdf(folder)
            sources = read_json(folder / "sources.json")
            pages = []
            with fitz.open(path) as pdf:
                state["total_pages"] = pdf.page_count
                write_json(folder / "state.json", state)
                for source_id, source in enumerate(sources, 1):
                    for number in range(source["start_page"], source["end_page"] + 1):
                        page = read_page(pdf[number-1])
                        pages.append(dict(page=number, source_id=source_id, source_name=source["name"],
                                          source_page=number-source["start_page"]+1, **page))
                        state["processed_pages"] = number
                        write_json(folder / "state.json", state)
            documents = suggest_segments(pages)
            protocol = build_protocol(documents, pages)
            out = folder / "output"
            out.mkdir(exist_ok=True)
            save_protocol(protocol, out / "protocolo.docx")
            payload = dict(job_id=job_id, total_pages=len(pages), pages=pages, documents=documents,
                           sources=sources, protocol=protocol, requires_review=any(p["requires_review"] for p in pages),
                           protocol_url=f"/trabajos/{job_id}/archivos/protocolo.docx")
            write_json(folder / "result.json", payload)
            state["status"] = "completed"
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception("Fallo al procesar el trabajo %s", job_id)
            state.update(status="failed", error=str(exc) if isinstance(exc, (ValueError, RuntimeError)) else
                         "No se pudo procesar el archivo. Verifique su formato y las dependencias.")
        write_json(folder / "state.json", state)


@app.get("/salud", response_model=schemas.Health, response_model_exclude_unset=True)
def health():
    return {"ok": True, "service": "sistema-notarial-mvp"}


@app.post("/procesar", status_code=202, response_model=schemas.Accepted)
async def process_files(background: BackgroundTasks, files: list[UploadFile] = File(...)):
    if not 1 <= len(files) <= 30:
        raise HTTPException(400, "Adjunte entre 1 y 30 archivos")
    job_id = uuid.uuid4().hex
    folder = DATA / job_id
    inputs = folder / "inputs"
    inputs.mkdir(parents=True)
    entries = []
    total = 0
    try:
        for index, upload in enumerate(files, 1):
            name = Path((upload.filename or "").replace("\\", "/")).name
            ext = Path(name).suffix.lower()
            if ext not in ALLOWED:
                raise HTTPException(415, f"Formato no soportado: {ext}")
            stored = f"{index:04d}{ext}"
            size = 0
            with (inputs / stored).open("wb") as target:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    total += len(chunk)
                    if size > 30 * 1024**2 or total > 150 * 1024**2:
                        raise HTTPException(413, "Límite de 30 MiB por archivo y 150 MiB por trabajo")
                    target.write(chunk)
            if not size:
                raise HTTPException(400, f"Archivo vacío: {name}")
            entries.append(dict(name=name, stored=stored))
        saved = [e["name"] for e in entries]
        write_json(folder / "inputs.json", entries)
        write_json(folder / "state.json", dict(status="queued", files=saved, processed_pages=0, total_pages=None))
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    background.add_task(process_job, job_id)
    return dict(job_id=job_id, status="queued", files=saved)


@app.get("/trabajos/{job_id}", response_model=schemas.State, response_model_exclude_unset=True)
def job_status(job_id: str):
    folder, state = locate(job_id)
    if state["status"] == "completed":
        state["result"] = read_json(folder / "result.json")
    return state


@app.get("/trabajos/{job_id}/resultado", response_model=schemas.Result, response_model_exclude_unset=True)
def job_result(job_id: str):
    folder, _ = completed(job_id)
    return read_json(folder / "result.json")


def download_url(job_id, filename, version):
    return f"/trabajos/{job_id}/archivos/{filename}?version={version}"


@app.post("/dividir", response_model=schemas.Split, response_model_exclude_unset=True)
def split_documents(body: SplitRequest):
    folder, state = completed(body.job_id)
    documents, specifications = [], []
    for i, doc in enumerate(body.documents, 1):
        name = (doc.name if doc.name is not None else f"Documento {i}").strip()
        if not name or not 1 <= doc.start_page <= doc.end_page <= state["total_pages"]:
            raise HTTPException(400, f"Rango o nombre inválido en documento {i}")
        filename = f"documento_{i:02d}.pdf"
        documents.append(dict(name=name, start_page=doc.start_page, end_page=doc.end_page, file=filename))
        specifications.append((filename, [(doc.start_page, doc.end_page)]))
    try:
        version = export(folder, specifications)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    for doc in documents:
        doc["url"] = download_url(body.job_id, doc["file"], version)
    return dict(job_id=body.job_id, documents=documents)


@app.post("/cortar", response_model=schemas.Cut, response_model_exclude_unset=True)
def cut_pages(body: CutRequest):
    folder, state = completed(body.job_id)
    try:
        ranges = parse_ranges(body.pages, state["total_pages"])
        version = export(folder, [("corte.pdf", ranges)])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return dict(job_id=body.job_id, file="corte.pdf", exported_pages=sum(b-a+1 for a,b in ranges),
                url=download_url(body.job_id, "corte.pdf", version=version))


@app.get("/trabajos/{job_id}/archivos/{filename}")
def download(job_id: str, filename: str, version: str | None = None):
    folder, _ = completed(job_id)
    if not re.fullmatch(r"(?:corte\.pdf|documento_\d+\.pdf|protocolo\.docx)", filename):
        raise HTTPException(404, "Archivo no encontrado")
    registry = folder / "exports.json"
    if version is None and registry.exists():
        version = read_json(registry).get(filename)
    out = folder / "output"
    if version is not None:
        if not re.fullmatch("[0-9a-f]{32}", version):
            raise HTTPException(404, "Exportación no encontrada")
        out /= version
    path = out / filename
    if not path.is_file():
        raise HTTPException(404, "Archivo no encontrado")
    return FileResponse(path, filename=filename)
