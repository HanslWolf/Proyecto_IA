import math
import cv2
import pymupdf as fitz
import numpy as np

from services.ocr_service import extract_page_text
from services.stamp_service import detect_stamps


def read_page(page):
    bounds = page.rect
    scale = min(200 / 72, 5000 / max(bounds.width, bounds.height),
                math.sqrt(9_000_000 / bounds.get_area()))
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
    image = cv2.cvtColor(np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3),
                         cv2.COLOR_RGB2BGR)
    stamps = detect_stamps(image)
    blocks = page.get_text("blocks", flags=fitz.TEXTFLAGS_BLOCKS & ~fitz.TEXT_PRESERVE_IMAGES)
    native = []
    mixed = image.copy()
    for block in blocks:
        text = block[4].strip()
        if not text or "\ufffd" in text:
            continue
        box = fitz.Rect(block[:4]) * page.rotation_matrix
        native.append((box.y0, box.x0, text))
    damaged_layer = any("\ufffd" in b[4] for b in blocks)
    if not native or damaged_layer:
        result = extract_page_text(image)
        result["requires_review"] |= damaged_layer
    else:
        pieces = native.copy()
        warnings = []
        any_ocr = False
        # Ocultar palabras nativas al leer imágenes de PDFs mixtos, incluso si
        # el PDF contiene una capa OCR superpuesta a una página escaneada.
        for word in page.get_text("words"):
            if "\ufffd" in word[4]:
                continue
            box = fitz.Rect(word[:4]) * page.rotation_matrix
            cv2.rectangle(mixed, (int(box.x0*scale)-1, int(box.y0*scale)-1),
                          (math.ceil(box.x1*scale)+1, math.ceil(box.y1*scale)+1), (255,255,255), -1)
        for info in page.get_image_info():
            box = (fitz.Rect(info["bbox"]) * page.rotation_matrix) & bounds
            if box.is_empty:
                continue
            x, y = max(0, int(box.x0*scale)), max(0, int(box.y0*scale))
            roi = mixed[y:math.ceil(box.y1*scale), x:math.ceil(box.x1*scale)]
            if roi.size < 100 or np.count_nonzero(roi.min(axis=2) < 170) < 40:
                continue
            read = extract_page_text(roi)
            pieces.append((box.y0, box.x0, read["text"]))
            if "warning" in read:
                warnings.append(read["warning"])
            roi[:] = 255
            any_ocr = True
        text = "\n\n".join(t for _, _, t in sorted(pieces, key=lambda p: p[:2]))
        result = dict(text=text, lines=text.splitlines(), confidence=None if any_ocr else 1.,
                      engine="mixed" if any_ocr else "native_pdf", requires_review=any_ocr)
        if warnings:
            result["warning"] = ". ".join(dict.fromkeys(warnings))
    result["stamps"] = stamps
    result["requires_review"] |= bool(stamps)
    return result
