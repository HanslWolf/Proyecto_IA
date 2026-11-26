# Contrato de integración del frontend

URL base local: `http://127.0.0.1:8000`. Swagger UI en `/docs`; especificación JSON en `/openapi.json`. Los ejemplos usan `ID` como marcador del identificador hexadecimal devuelto por el servidor. Las URL de descarga son relativas a la URL base.

| Método y ruta | Entrada | Éxito |
|---|---|---|
| GET /salud | Sin parámetros | 200 · {"ok":true,"service":"sistema-notarial-mvp"} |
| POST /procesar | multipart/form-data, campo repetido files en orden y area opcional | 202 · {"job_id":"ID","status":"queued","files":["acta.pdf"]} |
| GET /trabajos/{job_id} | ID en la ruta | 200 · status, files, processed_pages, total_pages y, cuando corresponde, error o result |
| GET /trabajos/{job_id}/resultado | ID en la ruta | 200 · Resultado completo al terminar |
| POST /dividir | JSON con job_id y documents | 200 · documents con name, start_page, end_page, file y url |
| POST /cortar | JSON con job_id y pages | 200 · job_id, file, exported_pages y url |
| GET /trabajos/{job_id}/archivos/{filename} | Opcional version en query para PDF | 200 · Archivo binario descargable (PDF o DOCX) |

## Carga y progreso

```powershell
curl.exe -F "files=@contrato.pdf" -F "files=@anexo.docx" http://127.0.0.1:8000/procesar
```

El campo multipart opcional area acepta contratos o personeria_juridica. Se guarda como metadato en el estado y en el resultado. Si se omite puede ser null. Ambos valores usan el mismo procesamiento documental.

Envía de 1 a 30 adjuntos. Máximo 30 MiB por archivo, 150 MiB por trabajo, 500 páginas combinadas. Admite PDF, DOC binario de Word, DOCX, PNG, JPEG, TIFF, BMP y WebP. En JavaScript, adjunta cada archivo con FormData.append("files", archivo); el navegador genera el encabezado multipart.

Consulta el estado cada segundo y termina el sondeo cuando recibas completed o failed. El código 202 confirma recepción del lote. La validación interna, conversión y OCR ocurren después. Un archivo corrupto puede devolver 202 y luego failed.

| status | Datos y acción de la interfaz |
|---|---|
| queued | En espera. total_pages puede ser null. |
| processing | Muestra processed_pages / total_pages cuando ya se conozca el total. |
| completed | result está disponible por compatibilidad y también se obtiene de /resultado. |
| failed | Muestra error. Un reenvío genera un nuevo ID. |

## Ejemplo del resultado

```json
{
  "job_id": "ID",
  "total_pages": 1,
  "sources": [{"name":"acta.pdf","start_page":1,"end_page":1}],
  "pages": [{
    "page":1,"source_id":1,"source_name":"acta.pdf","source_page":1,
    "text":"ACTA","lines":["ACTA"],"confidence":1.0,"engine":"native_pdf",
    "requires_review":false,"stamps":[]
  }],
  "documents":[{"name":"ACTA","start_page":1,"end_page":1}],
  "protocol":"ACTA.---","requires_review":false,
  "protocol_url":"/trabajos/ID/archivos/protocolo.docx"
}
```

Los motores posibles incluyen native_pdf, tesseract, paddleocr y mixed. En mixed, confidence es null porque combina fuentes con métricas diferentes. El valor 1 en extracción nativa indica lectura directa. warning puede explicar la falta de un motor. Cada sello candidato tiene text, confidence, requires_review y bbox = [izquierda, arriba, derecha, abajo], fracciones de 0 a 1 sobre la página visualizada. Un trabajo histórico de la versión anterior puede carecer de campos de procedencia, sellos o Word.

## División y corte

POST /dividir recibe segmentos aceptados o corregidos. name es opcional. Los límites son inclusivos. Ejemplo:

```json
{"job_id":"ID","documents":[{"name":"Contrato","start_page":1,"end_page":2},{"name":"Anexo","start_page":3,"end_page":3}]}
```

POST /cortar admite páginas sueltas, rangos y extremos abiertos. Con tres páginas, "3,1-2" exporta las páginas 3, 1 y 2 en ese orden. Repetir una página la repite en el PDF.

```json
{"job_id":"ID","pages":"3,1-2"}
```

Respuesta de ejemplo:

```json
{"job_id":"ID","file":"corte.pdf","exported_pages":3,"url":"/trabajos/ID/archivos/corte.pdf?version=VERSION"}
```

Usa la url devuelta en cada exportación para recuperar esa versión. La ruta antigua sin versión devuelve el archivo más reciente del mismo nombre. Máximo 2000 páginas de salida por operación.

## Errores

| HTTP | Significado |
|---|---|
| 400 | Archivo vacío, cantidad de adjuntos incorrecta o rango inválido |
| 404 | Trabajo, versión o archivo inexistente |
| 409 | Resultado o exportación solicitados antes de completed, o trabajo fallido |
| 413 | Carga demasiado grande |
| 415 | Extensión no admitida |
| 422 | Falta un campo obligatorio o su estructura/tipo no cumple el esquema |

Los errores del servicio siguen el formato `{"detail":"mensaje"}`. En 422, FastAPI devuelve detail como lista de errores con loc, msg y type. Los fallos de procesamiento asíncrono están en GET /trabajos/{job_id} con HTTP 200, status="failed" y error legible.
