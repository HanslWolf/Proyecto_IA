import os
from functools import lru_cache
import cv2
import pytesseract
from pytesseract import Output

def tesseract(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    data = pytesseract.image_to_data(gray, lang=os.getenv("TESSERACT_LANG", "spa"), output_type=Output.DICT)
    grouped, confidences = {}, []
    for i, value in enumerate(data["text"]):
        word = value.strip()
        if not word: continue
        try: conf = float(data["conf"][i])
        except (ValueError, TypeError): conf = -1
        if conf >= 0: confidences.append(conf)
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        grouped.setdefault(key, []).append((word, conf))
    lines = []
    for words in grouped.values():
        output, previous_bad = [], False
        for word, conf in words:
            if 0 <= conf < 45:
                if not previous_bad: output.append("ilegible")
                previous_bad = True
            else: output.append(word); previous_bad = False
        if output: lines.append(" ".join(output))
    score = sum(confidences) / len(confidences) / 100 if confidences else 0.0
    return {"text": "\n".join(lines), "lines": lines, "confidence": score, "engine": "tesseract", "requires_review": score < .55 or len("".join(lines)) < 30}

@lru_cache(maxsize=1)
def paddle_engine():
    from paddleocr import PaddleOCR
    return PaddleOCR(lang=os.getenv("PADDLEOCR_LANG", "latin"), use_angle_cls=True, show_log=False)

def paddle(image):
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB) if len(image.shape) == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
    raw = paddle_engine().ocr(rgb, cls=True); lines, scores = [], []
    if raw and raw[0]:
        for item in raw[0]:
            if item and len(item) >= 2:
                text, score = item[1]
                if text and text.strip(): lines.append(text.strip()); scores.append(float(score))
    score = sum(scores) / len(scores) if scores else 0.0
    return {"text": "\n".join(lines), "lines": lines, "confidence": score, "engine": "paddleocr", "requires_review": score < .70 or len("".join(lines)) < 30}

def extract_page_text(image):
    try: first = tesseract(image)
    except Exception as exc: first = {"text":"", "lines":[], "confidence":0.0, "engine":"tesseract_error", "requires_review":True, "warning":str(exc)}
    if not first["requires_review"]: return first
    try:
        second = paddle(image)
        if second["text"].strip() and len(second["text"]) > len(first["text"]): return second
    except Exception as exc: first["warning"] = f"PaddleOCR no disponible: {exc}"
    first["requires_review"] = True
    return first
