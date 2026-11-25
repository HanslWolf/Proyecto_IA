from pathlib import Path
import shutil
import subprocess
import tempfile
from io import BytesIO
from zipfile import is_zipfile, ZipFile

import pymupdf as fitz
from PIL import Image, ImageOps, ImageSequence
from utils.storage import read_json, write_json

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
MAX_PAGES = 500


def image_to_pdf(source: Path, target: Path):
    with Image.open(source) as image, fitz.open() as output:
        for frame in ImageSequence.Iterator(image):
            if output.page_count >= MAX_PAGES or frame.width * frame.height > 35_000_000:
                raise ValueError("Imagen fuera de los límites de páginas o resolución")
            rgb = ImageOps.exif_transpose(frame).convert("RGBA")
            with BytesIO() as stream:
                white = Image.new("RGB", rgb.size, "white")
                white.paste(rgb, mask=rgb.getchannel("A"))
                white.save(stream, format="PNG")
                page = output.new_page(width=rgb.width * .36, height=rgb.height * .36)
                page.insert_image(page.rect, stream=stream.getvalue())
        output.save(target)


def word_to_pdf(source: Path, outdir: Path):
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError("Instale LibreOffice y agregue soffice al PATH para procesar DOC/DOCX")
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run([soffice, "-env:UserInstallation=" + Path(profile).as_uri(),
                        "--headless", "--convert-to", "pdf", "--outdir", str(outdir), str(source)],
                       check=True, capture_output=True, timeout=180)
    target = outdir / f"{source.stem}.pdf"
    if not target.exists():
        raise ValueError("LibreOffice no pudo convertir el documento")
    return target


def validate_format(source: Path):
    ext = source.suffix.lower()
    if ext in IMAGE_EXT:
        expected = {".jpg": "JPEG", ".jpeg": "JPEG", ".tif": "TIFF", ".tiff": "TIFF"}
        with Image.open(source) as image:
            valid = image.format == expected.get(ext, ext[1:].upper())
    elif ext == ".docx":
        valid = is_zipfile(source)
        if valid:
            with ZipFile(source) as archive:
                valid = "word/document.xml" in archive.namelist()
    else:
        with source.open("rb") as stream:
            signature = stream.read(1024)
        valid = b"%PDF-" in signature if ext == ".pdf" else signature.startswith(bytes.fromhex("D0CF11E0A1B11AE1"))
    if not valid:
        raise ValueError(f"El contenido no corresponde a la extensión {ext}")


def prepare_pdf(job: Path) -> Path:
    temp = job / "conversion"
    temp.mkdir(exist_ok=True)
    sources = []
    with fitz.open() as combined:
        for entry in read_json(job / "inputs.json"):
            source = job / "inputs" / entry["stored"]
            ext = source.suffix.lower()
            validate_format(source)
            if ext == ".pdf":
                converted = source
            elif ext in IMAGE_EXT:
                converted = temp / f"{source.stem}.pdf"
                image_to_pdf(source, converted)
            else:
                converted = word_to_pdf(source, temp)
            with fitz.open(converted) as pdf:
                if not pdf.is_pdf or pdf.needs_pass or not pdf.page_count:
                    raise ValueError("Se requiere un PDF válido sin contraseña")
                if combined.page_count + pdf.page_count > MAX_PAGES:
                    raise ValueError(f"Máximo {MAX_PAGES} páginas por trabajo")
                start = combined.page_count + 1
                combined.insert_pdf(pdf)
                sources.append(dict(name=entry["name"], start_page=start, end_page=combined.page_count))
        target = job / "original.pdf"
        combined.save(target)
    write_json(job / "sources.json", sources)
    return target
