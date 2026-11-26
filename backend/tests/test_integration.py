import os
import unittest
from unittest.mock import patch
import cv2
import numpy as np
from ocr_neuronal import neural_ocr
from services import ocr_service


class IntegracionNeuronal(unittest.TestCase):
    def test_conserva_confianza_de_lineas(self):
        image = np.zeros((40, 90, 3), np.uint8)
        payload = {"error": None, "lines": ["ACTA", "duda"], "scores": [.98, .25]}
        with patch.object(neural_ocr, "extract_text", return_value=payload):
            result = ocr_service.paddle(image)
        self.assertEqual(result["text"], "ACTA ilegible")
        self.assertTrue(result["requires_review"])

    @unittest.skipUnless(os.getenv("NOTARIA_TEST_PADDLE") == "1", "Activar para probar con pesos reales")
    def test_respaldo_con_pesos_reales(self):
        image = np.full((250,1000,3), 255, np.uint8)
        cv2.putText(image, "ACTA DE PRUEBA", (35,140), cv2.FONT_HERSHEY_SIMPLEX, 2, (0,0,0), 4)
        # Aislar la condición de respaldo. La inferencia neuronal es real.
        with patch.object(ocr_service, "tesseract", side_effect=RuntimeError):
            result = ocr_service.extract_page_text(image)
        self.assertEqual(result["engine"], "paddleocr")
        self.assertIn("ACTA DE PRUEBA", result["text"].upper())
