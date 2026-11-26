"""
Módulo OCR neuronal basado en PaddleOCR

- Motor: PaddleOCR 3.7.0 (modelos móviles PP-OCRv5).
- Contrato de salida uniforme para integración con FastAPI.
"""

import os
from pathlib import Path
import logging
from typing import Dict, Any, Optional

import numpy as np
from .image_preprocessing import preprocess_for_ocr

# Configurar logging silencioso por defecto (PaddleOCR 3.x ya no acepta show_log)
logger = logging.getLogger(__name__)
try:
    from paddleocr import logger as paddle_logger
    paddle_logger.setLevel("ERROR")
except Exception:
    # Si la importación cambia entre versiones, no romper el módulo
    pass


# CONSTANTES DE CONFIGURACIÓN
# Umbral de confianza por debajo del cual el resultado se marca para revisión humana.
REVIEW_THRESHOLD = 0.85

# Idioma del reconocimiento ('es' = español)
DEFAULT_LANG = "es"

# CLASE PRINCIPAL
class NeuralOCR:

    _instance: Optional["NeuralOCR"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(NeuralOCR, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, lang: str = DEFAULT_LANG, use_gpu: bool = False):
        if getattr(self, "_initialized", False):
            return

        self.lang = lang
        self.device = "gpu" if use_gpu else "cpu"

        logger.info(
            f"Inicializando PaddleOCR (lang={lang}, device={self.device})... "
            "La primera vez puede tardar varios minutos por la descarga de modelos."
        )

        # Inicialización compatible con PaddleOCR

        from paddleocr import PaddleOCR
        names = {
            "text_detection": "PP-OCRv5_mobile_det",
            "text_recognition": "latin_PP-OCRv5_mobile_rec",
            "textline_orientation": "PP-LCNet_x1_0_textline_ori",
        }
        options = {}
        root = os.getenv("NOTARIA_MODELOS")
        local = Path(__file__).resolve().parents[1] / "modelos"
        if not root and local.is_dir():
            root = local
        for stage, name in names.items():
            options[f"{stage}_model_name"] = name
            if root:
                directory = Path(root) / name
                if not directory.is_dir():
                    raise FileNotFoundError(f"Falta el modelo {name} en NOTARIA_MODELOS")
                options[f"{stage}_model_dir"] = str(directory)
        self.ocr = PaddleOCR(
            **options, device=self.device, enable_mkldnn=False, cpu_threads=2,
            use_textline_orientation=True,
            use_doc_orientation_classify=False,  # No clasificar orientación del documento completo
            use_doc_unwarping=False,             # No "des-distorsionar" el documento completo
        )

        self._initialized = True
        logger.info("Modelo PaddleOCR inicializado correctamente.")


    def extract_text(self, image: np.ndarray) -> Dict[str, Any]:
        """
        Recibe una imagen BGR (NumPy / OpenCV) y devuelve un diccionario con:
        {
            "text": str,
            "lines": list[str],
            "confidence": float,
            "engine": "paddleocr",
            "requires_review": bool,
            "error": Optional[str]
        }
        """
        if image is None or not isinstance(image, np.ndarray):
            return self._error_result(
                "Entrada inválida: se esperaba un arreglo NumPy (imagen BGR)."
            )

        if image.size == 0:
            return self._error_result("La imagen está vacía.")

        try:
            results = self.ocr.predict(preprocess_for_ocr(image))

            if not results:
                return self._error_result(
                    None
                )

            # En 3.x, results es una lista de objetos/dicts con la información
            # de cada imagen procesada. Solo procesamos la primera.
            res = results[0]
            texts, scores = self._parse_result(res)

            if not texts:
                return self._error_result(
                    None
                )

            # Limpiar líneas vacías
            clean_lines: list[str] = []
            clean_scores: list[float] = []
            for t, s in zip(texts, scores):
                t_str = str(t).strip() if t is not None else ""
                if t_str:
                    clean_lines.append(t_str)
                    clean_scores.append(float(s) if s is not None else 0.0)

            if not clean_lines:
                return self._error_result(
                    None
                )

            # Confianza global ponderada por longitud de línea
            total_chars = sum(len(line) for line in clean_lines)
            if total_chars > 0:
                weighted_conf = (
                    sum(score * len(line) for score, line in zip(clean_scores, clean_lines))
                    / total_chars
                )
            else:
                weighted_conf = 0.0

            requires_review = weighted_conf < REVIEW_THRESHOLD

            return {
                "text": "\n".join(clean_lines),
                "lines": clean_lines,
                "scores": clean_scores,
                "confidence": round(float(weighted_conf), 4),
                "engine": "paddleocr",
                "requires_review": requires_review,
                "error": None,
            }

        except Exception as e:
            logger.exception("Error durante el reconocimiento OCR")
            return self._error_result(f"Error interno de OCR: {str(e)}")


    @staticmethod
    def _parse_result(res: Any) -> tuple[list[str], list[float]]:
        """
        Extrae textos y scores de un resultado de PaddleOCR 3.x.
        """
        data: Any = res

        # Caso 1: objeto con .json (dict) o .to_dict()
        if not isinstance(data, dict) and isinstance(getattr(data, "json", None), dict):
            data = data.json
        elif not isinstance(data, dict) and hasattr(data, "to_dict"):
            try:
                data = data.to_dict()
            except Exception:
                pass

        # Caso 2: si es dict, buscar las claves esperadas
        if isinstance(data, dict):
            inner = data.get("res", data)

            texts = inner.get("rec_texts", inner.get("rec_text", []))
            scores = inner.get("rec_scores", inner.get("rec_score", []))
            texts = [texts] if isinstance(texts, str) else list(texts)
            scores = [scores] if np.isscalar(scores) else list(scores)

            # Asegurar longitudes iguales
            if len(scores) < len(texts):
                scores = list(scores) + [0.0] * (len(texts) - len(scores))

            return list(texts), list(scores)

        # Caso 3: formato antiguo de lista [[box, (text, score)], ...]
        if isinstance(data, list):
            texts, scores = [], []
            for item in data:
                try:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        payload = item[1]
                        if isinstance(payload, (list, tuple)) and len(payload) >= 2:
                            texts.append(payload[0])
                            scores.append(payload[1])
                except Exception:
                    continue
            return texts, scores

        return [], []

    @staticmethod
    def _error_result(message: Optional[str]) -> Dict[str, Any]:
        """Devuelve un resultado uniforme indicando error controlado."""
        return {
            "text": "",
            "lines": [],
            "scores": [],
            "confidence": 0.0,
            "engine": "paddleocr",
            "requires_review": True,
            "error": message,
        }


# PARA EL BACKEND
_default_engine: Optional[NeuralOCR] = None


def get_ocr_engine(lang: str = DEFAULT_LANG, use_gpu: bool = False) -> NeuralOCR:
    """
    Devuelve la instancia única del motor. Si aún no existe, la crea.
    """
    global _default_engine
    if _default_engine is None:
        _default_engine = NeuralOCR(lang=lang, use_gpu=use_gpu)
    return _default_engine


def extract_text(image: np.ndarray) -> Dict[str, Any]:
    """
    Función pública de integración. El backend solo necesita importar esto:

        from backend.ocr_neuronal.neural_ocr import extract_text
        resultado = extract_text(image_bgr)

    El modelo se inicializa la primera vez y se reutiliza en las
    siguientes llamadas (patrón Singleton).
    """
    engine = get_ocr_engine()
    return engine.extract_text(image)

def recognize(image_bgr):
    """Contrato por línea para la selección híbrida del backend."""
    result = extract_text(image_bgr)
    if result["error"]:
        raise RuntimeError(result["error"])
    return [{"text": text, "confidence": score}
            for text, score in zip(result["lines"], result["scores"], strict=True)]
