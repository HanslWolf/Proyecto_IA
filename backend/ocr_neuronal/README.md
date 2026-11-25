# Entrada del módulo neuronal

Coloca aquí el módulo del equipo (por ejemplo motor.py) y sus pesos según las instrucciones de su autora. Configura NOTARIA_OCR_MODULE=ocr_neuronal.motor antes de iniciar Uvicorn. Instala las dependencias de ese módulo en el mismo entorno Python 3.11.

El módulo exporta recognize(image_bgr). Recibe un ndarray NumPy uint8 (alto, ancho, 3), con canales BGR. Devuelve una lista en orden de lectura. Ejemplo de salida:

    [{"text": "Contrato de servicios.", "confidence": 0.91}]

Devuelve [] cuando no reconoce texto y lanza una excepción si falla el motor. La confianza es decimal entre 0 y 1. El adaptador carga el proveedor al primer uso, en el mismo proceso, y serializa llamadas. También recibe recortes de posibles sellos. No cambies los endpoints para conectar otro proveedor.

Sin módulo configurado se intenta el adaptador de la API de PaddleOCR 2.x de la base original. Si tu instalación usa 3.x, implementa recognize con la API de tu versión y selecciona ese módulo. El MVP básico requiere únicamente Tesseract. Las dependencias y los pesos de Paddle no se distribuyen en el ZIP.

Aceptación con el módulo real: procesar la misma página de transcripción conocida con el módulo configurado, inspeccionar engine, warning y text, y comparar con el original. Una llamada neuronal no implica que su resultado será seleccionado. La prueba test_external_adapter verifica el contrato con un proveedor controlado.
