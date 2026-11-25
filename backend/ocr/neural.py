"""Adaptador del módulo opcional. Entrada BGR uint8, salida por líneas."""
import importlib
import os
from functools import lru_cache
from threading import Lock

import cv2

_lock = Lock()


@lru_cache(maxsize=1)
def provider():
    custom = os.getenv("NOTARIA_OCR_MODULE")
    if custom:
        return importlib.import_module(custom).recognize
    from paddleocr import PaddleOCR
    engine = PaddleOCR(lang=os.getenv("PADDLEOCR_LANG", "es"), use_angle_cls=True, show_log=False)

    def recognize(image):
        raw = engine.ocr(image, cls=True)
        return [dict(text=item[1][0], confidence=item[1][1]) for item in (raw[0] or [])] if raw else []
    return recognize


def recognize(image):
    with _lock:
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        return provider()(image)
