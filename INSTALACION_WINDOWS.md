# Instalación y verificación en Windows 10/11 x64

## 1. Incorporar el proyecto a tu copia Git

1. Descomprime el ZIP en una carpeta temporal. Abre la carpeta Proyecto del ZIP. Debes ver backend, frontend, README.md y API.md.
2. En la carpeta original IA\Proyecto abre PowerShell y ejecuta los comandos de abajo. Si git status muestra ediciones propias, guárdalas antes de copiar o compara los archivos en VS Code. Crea una rama para revisar la integración con tu equipo.
3. Copia el **contenido** de Proyecto del ZIP al nivel de la carpeta .git de tu repositorio. Acepta reemplazar los archivos de la versión anterior que correspondan. La entrega incluye la versión integrada del frontend y del módulo neuronal. Si ya tenías otra copia de orc_neuronal o venv_ocr fuera de backend, mantenla fuera del conjunto de archivos que agregues al commit.

```powershell
git rev-parse --show-toplevel
git status --short
git switch -c integracion/frontend-ocr
```

Si la rama ya existe, usa `git switch integracion/frontend-ocr`.

## 2. Verificar las herramientas del sistema

Instala Python 3.11 de 64 bits, Tesseract con el paquete español y LibreOffice con Writer. Estos dos últimos son programas de Windows. pip instala las librerías que los invocan. En PowerShell, desde IA\Proyecto:

```powershell
py -3.11 -c "import sys, struct; print(sys.version, struct.calcsize('P')*8)"
$env:Path += ";C:\Program Files\Tesseract-OCR;C:\Program Files\LibreOffice\program"
tesseract --list-langs
soffice --version
```

El primer comando debe indicar 3.11 y 64. El segundo programa debe listar spa. Si ya tienes spa.traineddata en otra carpeta configura TESSDATA_PREFIX con el directorio que contiene ese archivo. Adapta las rutas si instalaste los programas en otro lugar.

## 3. Crear un entorno independiente

Desde IA\Proyecto:

```powershell
cd backend
py -3.11 -m venv .venv-integrado
$py = ".\.venv-integrado\Scripts\python.exe"
& $py -m pip install --upgrade pip
& $py -m pip install -r requirements-neuronal.txt -r requirements-dev.txt
& $py -m pip check
& $py -c "import paddle, cv2; from importlib.metadata import version; print(paddle.__version__, version('paddleocr'), cv2.__version__)"
```

La combinación usada para la integración es PaddlePaddle 3.2.0 CPU, PaddleOCR 3.7.0, PaddleX 3.7.2 y opencv-contrib-python 4.10.0.84. requirements-neuronal incluye requirements.txt. El entorno fresco evita mezclar las dos distribuciones de OpenCV del entorno anterior. La primera instalación descarga paquetes grandes. Usa esta misma terminal para los siguientes pasos.

## 4. Preparar y probar los modelos

```powershell
& $py -m ocr_neuronal.preparar_modelos
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = "True"
$env:NOTARIA_TEST_PADDLE = "1"
Remove-Item Env:NOTARIA_OCR_MODULE -ErrorAction SilentlyContinue
& $py -m unittest discover -s tests -v
```

El primer comando necesita internet y escribe tres modelos oficiales en backend/modelos/. Comprueba el SHA-256 de cada archivo descargado. Si se interrumpe, vuelve a ejecutar el comando antes de iniciar el backend. En otra máquina también puedes copiar esa carpeta ya preparada. Opcionalmente, NOTARIA_MODELOS puede apuntar al directorio que contiene las tres subcarpetas de modelos. La aplicación busca backend/modelos por defecto. Mantén el backend detenido mientras preparas los pesos.

Con las dependencias, LibreOffice, spa y los pesos disponibles, el resultado esperado es **11 pruebas, OK, sin omisiones**. Durante las pruebas de archivos inválidos aparecen errores deliberados en consola. Mira el resumen de unittest. La prueba test_respaldo_con_pesos_reales induce un fallo en Tesseract y usa inferencia neuronal real con una imagen sintética. Sin NOTARIA_TEST_PADDLE=1 esa prueba se omite.

## 5. Arrancar los dos componentes

En la primera terminal, en backend:

```powershell
& $py -m uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1
```

En una segunda ventana PowerShell, desde IA\Proyecto:

```powershell
py -3.11 -m http.server 5500 --bind 127.0.0.1 --directory frontend
```

Abre [la interfaz](http://127.0.0.1:5500), [salud](http://127.0.0.1:8000/salud) o [el contrato interactivo](http://127.0.0.1:8000/docs). La interfaz utiliza módulos JavaScript y se sirve por HTTP. La URL de FastAPI está en frontend/js/app.js, CONFIG.API_BASE. Un proceso Uvicorn procesa los trabajos secuencialmente y guarda estados en disco. Para detener cualquiera de los servidores usa Ctrl+C en su terminal.

## 6. Prueba de aceptación del equipo

1. Prepara un PDF con texto seleccionable, una imagen escaneada y un DOCX de prueba. Elige un área y adjúntalos en un orden conocido. Inicia el procesamiento.
2. Comprueba área, páginas, archivos de origen y segmentos. Abre el detalle de una página para ver motor, texto y alerta o posibles sellos. native_pdf significa lectura directa. Una imagen clara puede resolverse con Tesseract. La prueba neuronal del paso 4 verifica el caso de respaldo independientemente.
3. Descarga protocolo.docx. Compara nombres, importes, fechas, abreviaturas y finales de párrafo con los originales. Busca - para punto seguido, .--- para punto y aparte e ilegible donde corresponda.
4. En los rangos, prueba una página superior al total. Debe mostrarse un error en el panel de resultados. Corrige los límites, aplica la división y abre los PDF descargables. En corte, prueba 2,1 sobre un trabajo de al menos dos páginas y verifica el orden.
5. Registra datos de prueba, versión de Git, sistema operativo, resultados observados y pendientes. Valida sellos y párrafos partidos entre páginas con personal de la notaría. La división exporta PDF; para corregir el texto del borrador, edita el Word descargado.

## 7. Compartir por Git

Desde IA\Proyecto, después de revisar y probar:

```powershell
git status --short
git add -- .gitignore backend frontend README.md API.md INSTALACION_WINDOWS.md PROMPT_DOCUMENTACION.md
git diff --cached --stat
git commit -m "Integra frontend notarial y respaldo PaddleOCR 3 en CPU"
git push -u origin integracion/frontend-ocr
```

Los modelos, entornos y expedientes de backend/data quedan fuera del commit. Verifica el listado antes del push. El paquete distribuido contiene código, pruebas y documentación.

## Fallos que puedes identificar

| Síntoma | Comprobación |
|---|---|
| La interfaz indica API sin conexión | Abre /salud, revisa la terminal de Uvicorn y la URL de CONFIG.API_BASE. |
| Falla una conversión Word | Comprueba soffice --version en la terminal que inició Uvicorn. Prueba un DOCX sencillo con Writer. |
| Tesseract aparece como no disponible | Comprueba tesseract --list-langs, spa y PATH desde esa misma terminal. |
| Falla el módulo neuronal | Ejecuta la prueba con pesos reales, revisa la primera excepción y verifica que pip y Uvicorn utilicen .venv-integrado. Si configuraste NOTARIA_MODELOS, comprueba que sus tres subcarpetas contengan inference.json, inference.yml e inference.pdiparams. |
| PowerShell deja de reconocer $py | La variable pertenece a esa sesión. Desde backend define de nuevo $py = ".\.venv-integrado\Scripts\python.exe". |
