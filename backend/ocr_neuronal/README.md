# OCR neuronal integrado

El proveedor predeterminado es ocr_neuronal.neural_ocr.recognize. Se basa en el módulo entregado por el equipo y llama a PaddleOCR.predict sobre una imagen NumPy BGR uint8. Reutiliza la instancia en el proceso y devuelve una lista ordenada con text y confidence por línea. Un resultado vacío es []; un fallo técnico genera una excepción. extract_text conserva la interfaz de diccionario y añade scores paralelos a lines.

Instala requirements-neuronal.txt en el entorno del backend. La configuración del MVP usa CPU, dos hilos, detector PP-OCRv5_mobile_det, reconocedor latin_PP-OCRv5_mobile_rec y orientación PP-LCNet_x1_0_textline_ori. El preprocesamiento suave es opcional en la utilidad de la autora; el flujo integrado conserva el BGR original. El adaptador del backend mantiene NOTARIA_OCR_MODULE para sustituir al proveedor si el equipo lo requiere. La conversión y el orden de páginas siguen siendo responsabilidad de services/document_service.py.

Prepara los pesos con python -m ocr_neuronal.preparar_modelos desde backend. Se buscan en backend/modelos/ o en NOTARIA_MODELOS si se define. Si no existe un directorio local configurado, Paddle puede intentar su descarga automática. Consulta INSTALACION_WINDOWS.md para instalar y probar la ruta local.
