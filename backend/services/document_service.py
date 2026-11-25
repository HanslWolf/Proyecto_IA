from pathlib import Path
import shutil, subprocess, tempfile
import fitz
from PIL import Image, ImageOps, ImageSequence
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}

def image_to_pdf(source: Path, target: Path):
    frames = []
    with Image.open(source) as image:
        for frame in ImageSequence.Iterator(image): frames.append(ImageOps.exif_transpose(frame.copy()).convert("RGB"))
    if not frames: raise ValueError(f"Imagen sin páginas: {source.name}")
    frames[0].save(target, "PDF", save_all=True, append_images=frames[1:])

def word_to_pdf(source: Path, outdir: Path):
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice: raise RuntimeError("Instale LibreOffice y agregue soffice al PATH para procesar DOC/DOCX")
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(outdir), str(source), f"-env:UserInstallation=file://{profile}"], check=True, capture_output=True, timeout=180)
    target = outdir / f"{source.stem}.pdf"
    if not target.exists(): raise RuntimeError(f"No se pudo convertir {source.name}")
    return target

def prepare_pdf(job: Path) -> Path:
    inputs, temp = job / "inputs", job / "conversion"; temp.mkdir(exist_ok=True)
    combined = fitz.open()
    try:
        for source in sorted(inputs.iterdir()):
            ext = source.suffix.lower()
            if ext == ".pdf": converted = source
            elif ext in IMAGE_EXT: converted = temp / f"{source.stem}.pdf"; image_to_pdf(source, converted)
            elif ext in {".doc", ".docx"}: converted = word_to_pdf(source, temp)
            else: raise ValueError(f"Formato no soportado: {source.name}")
            with fitz.open(converted) as pdf: combined.insert_pdf(pdf)
        if not combined.page_count: raise ValueError("No hay páginas para procesar")
        target = job / "original.pdf"; combined.save(target); return target
    finally: combined.close()
