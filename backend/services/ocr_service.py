import math
import os

import cv2
import pytesseract
from pytesseract import Output
from ocr import neural


def summarize(paragraphs, scores, engine):
    text = "\n\n".join(" ".join(p) for p in paragraphs if p)
    lines = [line for p in paragraphs for line in p]
    confidence = sum(scores) / len(scores) if scores else 0.
    return dict(text=text or "ilegible", lines=lines or ["ilegible"], confidence=confidence,
                engine=engine, requires_review=("ilegible" in text.lower() or confidence < .75 or len(text) < 30))


def tesseract(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    data = pytesseract.image_to_data(gray, lang=os.getenv("TESSERACT_LANG", "spa"),
                                     output_type=Output.DICT, timeout=90)
    paragraphs, scores = {}, []
    for i, value in enumerate(data["text"]):
        word = value.strip()
        if not word:
            continue
        confidence = max(0., float(data["conf"][i]) / 100)
        scores.append(confidence)
        group = (data["block_num"][i], data["par_num"][i])
        words = paragraphs.setdefault(group, {}).setdefault(data["line_num"][i], [])
        if confidence >= .45:
            words.append(word)
        elif not words or words[-1] != "ilegible":
            words.append("ilegible")
    return summarize([[" ".join(words) for words in lines.values()] for lines in paragraphs.values()],
                     scores, "tesseract")


def paddle(image):
    lines, scores = [], []
    for item in neural.recognize(image):
        score = float(item["confidence"])
        if not math.isfinite(score) or not 0 <= score <= 1 or not isinstance(item["text"], str):
            raise ValueError("Respuesta neuronal inválida")
        if item["text"].strip():
            scores.append(score)
            lines.append(item["text"].strip() if score >= .60 else "ilegible")
    return summarize([lines], scores, "paddleocr")


def extract_page_text(image, *, optional=False):
    warnings = []
    try:
        first = tesseract(image)
    except Exception as exc:
        first = summarize([], [], "tesseract_error")
        warnings.append(f"Tesseract no disponible ({type(exc).__name__})")
    if first["requires_review"]:
        try:
            second = paddle(image)
            # Una lectura corta de alta confianza puede omitir casi toda la página.
            def rank(result):
                return len(result["text"].replace("ilegible", "").strip()) * result["confidence"] ** 2
            if rank(second) > rank(first):
                first = second
        except Exception as exc:
            warnings.append(f"OCR neuronal no disponible ({type(exc).__name__})")
            if first["engine"] == "tesseract_error" and not optional:
                raise RuntimeError(". ".join(warnings) + ". Compruebe el idioma de Tesseract y el módulo neuronal.") from exc
    if warnings:
        first["warning"] = ". ".join(warnings)
    return first
