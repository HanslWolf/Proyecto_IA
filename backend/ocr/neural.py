"""Adaptador del módulo opcional. Entrada BGR uint8, salida por líneas."""
import importlib
import os
from functools import lru_cache
from threading import Lock

import cv2

_lock = Lock()


@lru_cache(maxsize=1)
def provider():
    name = os.getenv("NOTARIA_OCR_MODULE") or "ocr_neuronal.neural_ocr"
    return importlib.import_module(name).recognize


def recognize(image):
    with _lock:
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        return provider()(image)
