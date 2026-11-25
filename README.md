# Transcripción y generación de protocolos · GADLP

MVP local para procesar folders de Contratos y Personería Jurídica. Conserva los originales, reúne las páginas en el orden de carga y entrega el texto por página, los segmentos sugeridos y un borrador de protocolo en Word. Las reglas de escritura implementadas son las indicadas por el equipo. La aceptación notarial requiere cotejar el resultado con el expediente.

## Ejecutar en Windows con Python 3.11

Instala Python 3.11, Tesseract con el idioma español y LibreOffice. En PowerShell, desde la carpeta Proyecto:

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:Path += ";C:\Program Files\Tesseract-OCR;C:\Program Files\LibreOffice\program"
tesseract --list-langs
soffice --version
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1
```

Ajusta las rutas si elegiste otros directorios. Comprueba que aparezca `spa`. Si usas una carpeta de modelos personalizada, configura `TESSDATA_PREFIX` con la ruta de la carpeta que contiene `spa.traineddata`.

En otra terminal, desde Proyecto:

```powershell
py -3.11 -m http.server 5500 --bind 127.0.0.1 --directory frontend
```

Abre [la demo](http://127.0.0.1:5500) o [Swagger UI](http://127.0.0.1:8000/docs). La demo muestra el orden de envío al seleccionar los adjuntos. Procesa, inspecciona cada página y descarga el DOCX o los PDF. En Linux, usa `python3.11 -m venv .venv` y `.venv/bin/python` desde backend. Los paquetes de sistema equivalentes en Debian/Ubuntu son `tesseract-ocr`, `tesseract-ocr-spa` y `libreoffice-writer`.

## Qué cambió y por qué

| Archivo | Causa y cambio |
|---|---|
| backend/main.py, utils/storage.py | El estado estaba solo en memoria. Cada trabajo tiene un directorio propio y JSON publicados mediante reemplazo atómico. Al reiniciar, los trabajos terminados siguen disponibles y los interrumpidos quedan en failed con motivo. |
| services/document_service.py | El orden alfabético y los nombres repetidos alteraban el expediente. Un manifiesto conserva cada adjunto, su posición y sus páginas. Se comprueba su tipo al procesarlo. Los DOC/DOCX usan LibreOffice con perfil aislado. Los TIFF multipágina conservan los fotogramas. |
| services/page_service.py | El umbral de 40 caracteres descartaba textos nativos breves y omitía imágenes en páginas mixtas. Se lee la capa nativa y se aplica OCR a regiones de imagen, ocultando previamente las palabras nativas. Una capa con caracteres de reemplazo se vuelve a leer por OCR. |
| services/ocr_service.py, ocr/neural.py | Tesseract se evalúa por confianza, longitud y marcas ilegibles. Se consulta el respaldo cuando corresponde. Se selecciona una lectura por región, ponderando cobertura y confianza. La salida conserva saltos entre párrafos reconocidos por Tesseract. |
| services/stamp_service.py | Faltaba detección de sellos. OpenCV busca contornos cerrados con tinta cromática, proporciones y densidad compatibles. Se lee el interior y se entregan ubicación y texto como anotaciones para cotejo. |
| services/segmentation_service.py | Cada archivo inicia un segmento. Un título distinto en las primeras líneas propone otro comienzo. Un encabezado idéntico al título activo continúa el segmento. |
| services/protocol_service.py | Se implementó el punto seguido, la marca de ilegibilidad por página y el DOCX. Los títulos generados para identificar segmentos permanecen en los metadatos. |
| services/export_service.py | Las exportaciones anteriores se sobrescribían. Cada operación válida publica sus archivos en una versión propia y mantiene las rutas de descarga anteriores. |
| schemas.py, frontend/api.js, frontend/index.html | Esquemas de respuesta OpenAPI, cliente reutilizable y pantalla de demostración. El frontend del equipo puede importar NotariaAPI y configurar su URL base. |
| tests/test_mvp.py | Pruebas de OCR, formatos, fidelidad, integración HTTP, exportación y recuperación. |

## Fidelidad y alcance

- El texto nativo se toma de los bloques ordenados por posición. Una línea ajustada al ancho del bloque continúa el párrafo. El final de bloque OCR/nativo y el final de página cierran un párrafo en este MVP. Un párrafo que continúa en otra hoja requiere cotejo. Columnas, tablas, encabezados repetidos y sellos sobre texto también pueden alterar el orden inferido.
- Ejemplo: `La Dra. Pérez verificó el folio. Consta.` → `La Dra. Pérez verificó el folio- Consta.---`. Se protegen decimales, iniciales y abreviaturas frecuentes. La lista de abreviaturas es ajustable.
- Las palabras con confianza Tesseract inferior a 0,45 se marcan `ilegible`. Las líneas neuronales inferiores a 0,60 también. Una confianza media inferior a 0,75, texto muy corto o marcas de ilegibilidad activan revisión. Los valores iniciales requieren calibración con los documentos de la notaría.
- Si ambos motores fallan técnicamente al leer contenido necesario, el trabajo queda en `failed`. Una página procesada sin texto reconocible produce `ilegible.---`. La confianza OCR expresa la estimación del motor y no mide la exactitud jurídica.
- La lectura específica de sellos aparece en `pages[].stamps`. El OCR de página puede haber leído también la inscripción. Por fidelidad, el generador no inserta una segunda copia automática del recorte. Un sello ausente del cuerpo se debe revisar e incorporar manualmente en el DOCX. Sellos negros, tenues o incompletos pueden pasar inadvertidos. Un logotipo de color puede generar un candidato.
- La segmentación propone límites entre páginas, con índices desde 1. Varios documentos en una misma hoja requieren revisión. La API permite ajustar los rangos enviados a /dividir. Esta operación exporta los PDF y conserva el resultado original.
- Procesamiento local con un proceso Uvicorn y un trabajo OCR activo a la vez. Las solicitudes se aceptan en segundo plano. No iniciar varios workers sobre el mismo directorio. Los cambios de estado se guardan en disco, sin reintento automático de trabajos interrumpidos. El operador puede reenviar los archivos.
- La demo usa HTTP local sin autenticación. El directorio de expedientes conserva entradas, conversiones y resultados hasta su eliminación por el operador. Para validar calidad, usar expedientes autorizados y comparar nombres, números, orden, marcas de ilegibilidad, límites y sellos con una transcripción revisada.

## Parámetros de entorno

| Variable | Valor inicial | Uso |
|---|---|---|
| NOTARIA_DATA | backend/data/jobs | Directorio de trabajos |
| NOTARIA_ORIGINS | * | Orígenes CORS separados por coma, p. ej. http://127.0.0.1:5500 |
| TESSERACT_LANG | spa | Idioma instalado para Tesseract |
| NOTARIA_OCR_MODULE | sin definir | Módulo Python del equipo que exporta recognize(image_bgr) |
| PADDLEOCR_LANG | es | Idioma para el adaptador opcional PaddleOCR 2.x |

Consulta [el contrato del módulo neuronal](backend/ocr_neuronal/README.md) y [el contrato REST](API.md).

## Pruebas

Desde backend, usando el mismo entorno de ejecución:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

La suite genera sus archivos en directorios temporales. Prueba la lectura de un sello sintético, una página mixta, PDF nativo, documentos Word, conservación de orden con nombres repetidos, segmentación, reglas, fallos y exportaciones. La prueba de LibreOffice se omite si el ejecutable no está disponible. La prueba de OCR requiere el modelo del idioma configurado. El proveedor neuronal de prueba implementa la interfaz acordada y se reemplaza por el módulo del equipo para la validación final.
