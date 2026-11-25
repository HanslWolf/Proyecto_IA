import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import cv2
import pymupdf as fitz
from docx import Document
from fastapi.testclient import TestClient
from PIL import Image
import pytesseract
import main
from ocr import neural
from services import ocr_service
from services.protocol_service import format_paragraph
from utils.storage import write_json


def pdf(*lines):
    with fitz.open() as doc:
        for line in lines:
            doc.new_page().insert_text((60, 80), line)
        return doc.tobytes()


def png_image():
    image = np.full((370, 1100, 3), 255, np.uint8)
    cv2.putText(image, "CONTRATO DE PRUEBA", (35, 85), cv2.FONT_HERSHEY_SIMPLEX, 2, (0,0,0), 3)
    cv2.circle(image, (835, 255), 76, (165, 60, 0), 6)
    cv2.putText(image, "SELLO", (783, 263), cv2.FONT_HERSHEY_SIMPLEX, 1, (165,60,0), 2)
    return cv2.imencode(".png", image)[1].tobytes()


class Backend(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        override = patch.object(main, "DATA", Path(tmp.name))
        override.start()
        self.addCleanup(override.stop)
        self.api = TestClient(main.app)
        self.api.__enter__()
        self.addCleanup(self.api.__exit__, None, None, None)

    def submit(self, files):
        res = self.api.post("/procesar", files=[("files", (name, data)) for name,data in files])
        self.assertEqual(res.status_code, 202, res.text)
        return res.json()["job_id"]

    def result(self, files):
        job = self.submit(files)
        state = self.api.get("/trabajos/" + job).json()
        self.assertEqual(state["status"], "completed", state)
        return self.api.get(f"/trabajos/{job}/resultado").json()

    def test_order_exports_and_compatibility(self):
        result = self.result([("z.pdf", pdf("Uno. Dos.", "Tres.")), ("a.pdf", pdf("Cuatro.")),
                              ("a.pdf", pdf("Cinco."))])
        self.assertEqual(result["protocol"], "Uno- Dos.--- Tres.--- Cuatro.--- Cinco.---")
        self.assertEqual([p["source_page"] for p in result["pages"]], [1,2,1,1])
        job = result["job_id"]
        doc = Document(io.BytesIO(self.api.get(result["protocol_url"]).content))
        self.assertEqual(doc.paragraphs[0].text, result["protocol"])
        split = self.api.post("/dividir", json=dict(job_id=job, documents=result["documents"])).json()
        self.assertEqual(len(split["documents"]), 3)
        for d in split["documents"]:
            with fitz.open(stream=self.api.get(d["url"]).content) as part:
                self.assertEqual(len(part), d["end_page"]-d["start_page"]+1)
        def cut(pages):
            return self.api.post("/cortar", json=dict(job_id=job, pages=pages)).json()
        previous = cut("4,1-2")
        latest = cut("2")
        for url, expected in [(previous["url"], ["Cinco.", "Uno. Dos.", "Tres."]),
                              (latest["url"].split("?")[0], ["Tres."])]:
            with fitz.open(stream=self.api.get(url).content) as part:
                self.assertEqual([p.get_text().strip() for p in part], expected)
        self.assertEqual(self.api.post("/cortar",json=dict(job_id=job,pages="50")).status_code,400)

    def test_real_scan_stamp_and_mixed_page(self):
        self.assertIn(os.getenv("TESSERACT_LANG","spa"), pytesseract.get_languages(config=""))
        image = png_image()
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text((40, 45), "Primera parte.")
            page.insert_image(fitz.Rect(40, 80, 560, 255), stream=image)
            mixed = doc.tobytes()
        result = self.result([("scan.png", image), ("mixto.pdf", mixed)])
        scan, mixed = result["pages"]
        self.assertIn("CONTRATO", scan["text"].upper())
        self.assertEqual(scan["engine"], "tesseract")
        self.assertTrue(scan["stamps"] and scan["requires_review"])
        self.assertIn("SELLO", scan["stamps"][0]["text"].upper())
        self.assertEqual(mixed["engine"], "mixed")
        self.assertEqual(mixed["text"].count("Primera parte."), 1)
        self.assertIn("CONTRATO", mixed["text"].upper())

    @unittest.skipUnless(shutil.which("soffice") or shutil.which("libreoffice"), "Requiere LibreOffice")
    def test_word_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            doc = Document()
            doc.add_paragraph("Acta de prueba.")
            doc.save(temp / "acta.docx")
            subprocess.run([shutil.which("soffice") or shutil.which("libreoffice"),
                            "-env:UserInstallation=" + (temp/"profile").as_uri(),
                            "--headless", "--convert-to", "doc:MS Word 97", "--outdir", str(temp),
                            str(temp / "acta.docx")], check=True, capture_output=True, timeout=120)
            result = self.result([(name, (temp/name).read_bytes()) for name in ("acta.docx","acta.doc")])
        self.assertEqual(result["protocol"].count("Acta de prueba.---"), 2)

    def test_errors_and_recovery(self):
        self.assertTrue(self.api.get("/salud").json()["ok"])
        for name, data, status in [("x.bin", b"x", 415), ("x.pdf", b"", 400)]:
            self.assertEqual(self.api.post("/procesar", files={"files": (name,data)}).status_code,status)
        job = self.submit([("x.pdf", b"invalid")])
        self.assertEqual(self.api.get("/trabajos/"+job).json()["status"], "failed")
        self.assertEqual(self.api.get(f"/trabajos/{job}/resultado").status_code, 409)
        self.assertEqual(self.api.get("/trabajos/desconocido").status_code, 404)
        write_json(main.DATA / job / "state.json", {"status": "processing"})
        with TestClient(main.app) as restarted:
            self.assertIn("interrumpido",restarted.get("/trabajos/"+job).json()["error"])

    def test_new_headings_and_blank_page(self):
        result = self.result([("lote.pdf",pdf("CONTRATO", "CONTRATO", "RESOLUCION", ""))])
        self.assertEqual([(d["start_page"],d["end_page"]) for d in result["documents"]],[(1,2),(3,4)])
        self.assertTrue(result["protocol"].endswith("ilegible.---"))
        self.assertTrue(result["requires_review"])

    def test_image_formats_and_tiff_order(self):
        files = []
        with Image.open(io.BytesIO(png_image())) as image:
            for fmt, name in [("JPEG","hoja.jpeg"),("BMP","hoja.bmp"),("WEBP","hoja.webp")]:
                stream = io.BytesIO()
                image.save(stream,format=fmt)
                files.append((name,stream.getvalue()))
            stream = io.BytesIO()
            blank = Image.new("RGB",image.size,"white")
            image.save(stream,format="TIFF",save_all=True,append_images=[blank])
            files.append(("hojas.tif",stream.getvalue()))
        result = self.result(files)
        self.assertEqual(result["total_pages"],5)
        self.assertEqual([p["source_page"] for p in result["pages"]], [1,1,1,1,2])
        for page in result["pages"][:-1]:
            self.assertIn("CONTRATO",page["text"].upper())
        self.assertEqual(result["pages"][-1]["text"], "ilegible")

    def test_unavailable_engines(self):
        with patch.object(ocr_service, "tesseract", side_effect=RuntimeError), \
                patch.object(ocr_service, "paddle", side_effect=ImportError):
            job = self.submit([("scan.png",png_image())])
        state = self.api.get("/trabajos/" + job).json()
        self.assertEqual(state["status"], "failed")
        self.assertIn("Tesseract", state["error"])

    def test_external_adapter(self):
        import types
        module = types.ModuleType("prueba_neuronal")
        module.recognize = lambda image: [dict(text="Texto reconocido por el adaptador neuronal.",confidence=.94)]
        neural.provider.cache_clear()
        self.addCleanup(neural.provider.cache_clear)
        with patch.dict("sys.modules", prueba_neuronal=module), patch.dict(os.environ, NOTARIA_OCR_MODULE=module.__name__):
            result = ocr_service.extract_page_text(np.full((80,300,3),255,np.uint8))
        self.assertEqual(result["engine"],"paddleocr")
        self.assertEqual(result["text"].count("Texto reconocido"),1)

    def test_rules(self):
        self.assertEqual(format_paragraph("La Dra. Díaz pagó 20.50 Bs. al Sr. Pérez. Consta."),
                         "La Dra. Díaz pagó 20.50 Bs. al Sr. Pérez- Consta.---")
