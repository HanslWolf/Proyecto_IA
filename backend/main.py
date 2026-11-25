from __future__ import annotations
import json, shutil, uuid
from pathlib import Path
from typing import Any
import fitz
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from services.document_service import prepare_pdf
from services.ocr_service import extract_page_text
from services.segmentation_service import suggest_segments
from services.protocol_service import build_protocol

BASE = Path(__file__).resolve().parent
DATA = BASE / "data" / "jobs"
DATA.mkdir(parents=True, exist_ok=True)
ALLOWED = {".pdf", ".doc", ".docx", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
app = FastAPI(title="Sistema Notarial MVP", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
jobs: dict[str, dict[str, Any]] = {}

class SplitRequest(BaseModel):
    job_id: str
    documents: list[dict[str, Any]] = Field(min_length=1)
class CutRequest(BaseModel):
    job_id: str
    pages: str

def locate(job_id: str):
    folder = DATA / job_id
    state = jobs.get(job_id)
    if not folder.is_dir() or state is None:
        raise HTTPException(404, "Trabajo no encontrado")
    return folder, state

def process_job(job_id: str):
    folder = DATA / job_id
    try:
        jobs[job_id].update(status="processing", processed_pages=0)
        pdf_path = prepare_pdf(folder)
        pages = []
        with fitz.open(pdf_path) as pdf:
            jobs[job_id]["total_pages"] = pdf.page_count
            for index, page in enumerate(pdf):
                native = page.get_text("text").strip()
                if len(native) >= 40:
                    lines = [x.strip() for x in native.splitlines() if x.strip()]
                    result = dict(text=native, lines=lines, confidence=1.0, engine="native_pdf", requires_review=False)
                else:
                    pix = page.get_pixmap(dpi=200, alpha=False)
                    import numpy as np, cv2
                    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                    if pix.n == 3:
                        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
                    result = extract_page_text(image)
                pages.append({"page": index + 1, **result})
                jobs[job_id]["processed_pages"] = index + 1
        documents = suggest_segments(pages)
        protocol = build_protocol(documents, pages)
        payload = {"job_id": job_id, "total_pages": len(pages), "pages": pages, "documents": documents,
                   "protocol": protocol, "requires_review": any(p["requires_review"] for p in pages)}
        (folder / "result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        jobs[job_id].update(status="completed", result=payload)
    except Exception as exc:
        jobs[job_id].update(status="failed", error=str(exc))

@app.get("/salud")
def health():
    return {"ok": True, "service": "sistema-notarial-mvp"}

@app.post("/procesar", status_code=202)
async def process_files(background: BackgroundTasks, files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(400, "Adjunte al menos un archivo")
    job_id = uuid.uuid4().hex
    folder = DATA / job_id
    inputs = folder / "inputs"
    inputs.mkdir(parents=True)
    saved = []
    try:
        for upload in files:
            name = Path(upload.filename or "documento").name
            if Path(name).suffix.lower() not in ALLOWED:
                raise HTTPException(415, f"Formato no soportado: {Path(name).suffix}")
            content = await upload.read()
            if not content:
                raise HTTPException(400, f"Archivo vacío: {name}")
            if len(content) > 30 * 1024 * 1024:
                raise HTTPException(413, f"Archivo supera 30 MB: {name}")
            (inputs / name).write_bytes(content)
            saved.append(name)
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    jobs[job_id] = {"status": "queued", "files": saved, "processed_pages": 0, "total_pages": None}
    background.add_task(process_job, job_id)
    return {"job_id": job_id, "status": "queued", "files": saved}

@app.get("/trabajos/{job_id}")
def job_status(job_id: str):
    _, state = locate(job_id)
    return state

@app.get("/trabajos/{job_id}/resultado")
def job_result(job_id: str):
    _, state = locate(job_id)
    if state["status"] != "completed":
        raise HTTPException(409, "El procesamiento todavía no terminó")
    return state["result"]

@app.post("/dividir")
def split_documents(body: SplitRequest):
    folder, state = locate(body.job_id)
    if state["status"] != "completed":
        raise HTTPException(409, "El trabajo todavía no terminó")
    out = folder / "output"
    out.mkdir(exist_ok=True)
    generated = []
    with fitz.open(folder / "original.pdf") as source:
        for i, doc in enumerate(body.documents, 1):
            name = str(doc.get("name", f"Documento {i}")).strip()
            start, end = int(doc.get("start_page", 0)), int(doc.get("end_page", 0))
            if not name or not (1 <= start <= end <= source.page_count):
                raise HTTPException(400, f"Rango inválido para {name or i}")
            part = fitz.open(); part.insert_pdf(source, from_page=start-1, to_page=end-1)
            filename = f"documento_{i:02d}.pdf"; part.save(out / filename); part.close()
            generated.append({"name": name, "start_page": start, "end_page": end, "file": filename})
    return {"job_id": body.job_id, "documents": generated}

def parse_ranges(value: str, total: int):
    result = []
    for item in value.split(","):
        item = item.strip()
        if not item: continue
        if "-" in item:
            a, b = item.split("-", 1); start = int(a) if a.strip() else 1; end = int(b) if b.strip() else total
        else: start = end = int(item)
        if not (1 <= start <= end <= total): raise ValueError(f"Rango inválido: {item}")
        result.append((start, end))
    if not result: raise ValueError("Indique páginas, por ejemplo 2-5 o 1,3,6-8")
    return result

@app.post("/cortar")
def cut_pages(body: CutRequest):
    folder, state = locate(body.job_id)
    if state["status"] != "completed": raise HTTPException(409, "El trabajo todavía no terminó")
    out = folder / "output"; out.mkdir(exist_ok=True)
    try:
        with fitz.open(folder / "original.pdf") as source:
            ranges = parse_ranges(body.pages, source.page_count)
            result = fitz.open()
            for a, b in ranges: result.insert_pdf(source, from_page=a-1, to_page=b-1)
            result.save(out / "corte.pdf"); count = result.page_count; result.close()
    except ValueError as exc: raise HTTPException(400, str(exc))
    return {"job_id": body.job_id, "file": "corte.pdf", "exported_pages": count}

@app.get("/trabajos/{job_id}/archivos/{filename}")
def download(job_id: str, filename: str):
    from fastapi.responses import FileResponse
    folder, _ = locate(job_id); path = folder / "output" / Path(filename).name
    if not path.is_file(): raise HTTPException(404, "Archivo no encontrado")
    return FileResponse(path, filename=path.name)
