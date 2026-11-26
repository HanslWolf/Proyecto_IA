# image_preprocessing.py
"""
Preprocesamiento opcional para mejorar el OCR en documentos notariales.

"""

import cv2
import numpy as np


def _ensure_3_channels(img: np.ndarray) -> np.ndarray:
    """Garantiza que la imagen tenga 3 canales (BGR)."""
    if img is None:
        return img
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 1:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 4:
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    return img


def preprocess_for_ocr(image: np.ndarray, apply: bool = False) -> np.ndarray:
    """
    Preprocesamiento suave para OCR.
    Parámetros
    ----------
    image : np.ndarray
        Imagen BGR de entrada.
    apply : bool
        Si es False (por defecto), devuelve la imagen sin cambios.
        Esto es deliberado: PaddleOCR es muy robusto por sí solo y el
        preprocesamiento agresivo suele EMPEORAR el resultado en
        documentos con sellos o texto tenue.

    Devuelve
    --------
    np.ndarray
        Imagen BGR de 3 canales, lista para PaddleOCR.
    """
    if image is None:
        return image

    # Garantizar 3 canales incluso si no se aplica preprocesamiento
    image = _ensure_3_channels(image)

    if not apply:
        return image

    # 1. Escala de grises SOLO para procesar, no para devolver
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # 2. Reducción de ruido suave (preserva bordes de sellos y trazos finos)
    denoised = cv2.fastNlMeansDenoising(gray, h=10)

    # 3. Mejora de contraste local con CLAHE
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(denoised)

    # 4. Reconstruir a 3 canales BGR para PaddleOCR
    return cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)