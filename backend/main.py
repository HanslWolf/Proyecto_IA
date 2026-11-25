# -*- coding: utf-8 -*-
"""Servicio Python: separa un PDF en documentos y genera el «protocolo».

Flujo de un trabajo (carpeta /data/trabajos/<id>):
  original.pdf  -> /procesar  -> paginas.json (análisis de cada página)
                              -> estado.json  (progreso / resultado)
                              -> salida/      (PDF por documento, protocolo.docx/.txt, SVG vectorizados)
  /dividir      -> rehace la salida con otros rangos de páginas (sin repetir el OCR)

Reglas del protocolo:
  * todo en un solo párrafo, sin saltos de línea;
  * cada punto (punto seguido) se escribe como un guion «-»;
  * cada punto y aparte (fin de párrafo) se escribe como un punto y 3 guiones «.---»;
  * lo que no se lee se escribe «ilegible».
"""
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import traceback
import unicodedata
from difflib import get_close_matches
from pathlib import Path
from typing import List, Optional

import cv2
import fitz  # PyMuPDF
import numpy as np
import pytesseract
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from fastapi import BackgroundTasks, FastAPI, HTTPException
from PIL import Image, ImageOps, ImageSequence
from pydantic import BaseModel
from pytesseract import Output

DPI = 200
RES_IMG_PDF = 200.0     # píxeles por pulgada al convertir una imagen en página PDF
UMBRAL_PALABRA = 45     # confianza mínima (0-100) para aceptar una palabra del OCR
UMBRAL_SELLO = 50       # confianza mínima para aceptar una palabra de un sello
FUENTE = "Times New Roman"
EXT_WORD = {".doc", ".docx"}
EXT_IMAGEN = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}

app = FastAPI(title="Protocolo de documentos")


# ------------------------------------------------------------------ utilidades
def sin_acentos(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def escribir_json(ruta: str, obj) -> None:
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, ruta)


def leer_json(ruta: str):
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def slug(s: str) -> str:
    s = sin_acentos(s).lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return (s or "documento")[:60]


def limpiar_control(s: str) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", s)


# ------------------------------------------------------------------ imagen y OCR
def renderizar(pagina) -> np.ndarray:
    pix = pagina.get_pixmap(dpi=DPI, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 1:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    return cv2.cvtColor(img[:, :, :3], cv2.COLOR_RGB2BGR)


def texto_nativo(pagina):
    """Si el PDF ya trae texto, se usa tal cual (sin OCR)."""
    if len(pagina.get_text().strip()) < 40:
        return None
    lineas, parrafos = [], []
    for b in pagina.get_text("blocks", sort=True):
        if b[6] != 0:
            continue
        ls = [l.strip() for l in b[4].splitlines() if l.strip()]
        if ls:
            lineas += ls
            parrafos.append(" ".join(ls))
    return lineas, parrafos, 100.0


# ------------------------------------------------------------------ archivos de entrada
def _rgb_blanco(img):
    """Convierte a RGB poniendo fondo blanco a la transparencia."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        fondo = Image.new("RGB", img.size, (255, 255, 255))
        rgba = img.convert("RGBA")
        fondo.paste(rgba, mask=rgba.getchannel("A"))
        return fondo
    return img.convert("RGB")


def cargar_imagenes(ruta: str):
    """Devuelve las páginas de una imagen (soporta TIFF/GIF multipágina), ya derechas y en RGB."""
    imagenes = []
    with Image.open(ruta) as im:
        for cuadro in ImageSequence.Iterator(im):
            limpio = ImageOps.exif_transpose(cuadro.copy())
            imagenes.append(_rgb_blanco(limpio))
    return imagenes


def insertar_imagen(doc, img) -> None:
    ancho = max(1.0, img.width * 72.0 / RES_IMG_PDF)
    alto = max(1.0, img.height * 72.0 / RES_IMG_PDF)
    pagina = doc.new_page(width=ancho, height=alto)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    pagina.insert_image(pagina.rect, stream=buf.getvalue())


def word_a_pdf(ruta: str, carpeta_temporal: str) -> str:
    """Convierte .doc/.docx a PDF con LibreOffice sin cuenta ni registro."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError("No está instalado LibreOffice para convertir archivos Word")
    perfil = Path(os.path.abspath(os.path.join(carpeta_temporal, "perfil_lo"))).as_uri()
    cmd = [
        soffice, "--headless", "--norestore", "--nologo",
        "-env:UserInstallation=" + perfil,
        "--convert-to", "pdf", "--outdir", carpeta_temporal, ruta,
    ]
    entorno = dict(os.environ)
    entorno["HOME"] = carpeta_temporal
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       timeout=300, env=entorno)
    except subprocess.CalledProcessError as e:
        detalle = (e.stderr or b"").decode("utf-8", "ignore").strip()
        raise RuntimeError(
            "LibreOffice no pudo convertir «%s»%s"
            % (os.path.basename(ruta), (": " + detalle) if detalle else "")
        )
    esperado = os.path.join(
        carpeta_temporal, os.path.splitext(os.path.basename(ruta))[0] + ".pdf"
    )
    if os.path.isfile(esperado):
        return esperado
    for nombre in os.listdir(carpeta_temporal):
        if nombre.lower().endswith(".pdf"):
            return os.path.join(carpeta_temporal, nombre)
    raise RuntimeError("LibreOffice no generó el PDF de «%s»" % os.path.basename(ruta))


def preparar_pdf(carpeta: str, archivos: List[str]) -> List[dict]:
    """Une PDF, Word e imágenes en un solo original.pdf y registra el origen de cada página."""
    entradas = os.path.join(carpeta, "entradas")
    try:
        nombres = leer_json(os.path.join(entradas, "nombres.json"))
    except Exception:
        nombres = {}
    doc = fitz.open()
    origenes = []
    for indice, archivo in enumerate(archivos, 1):
        nombre = os.path.basename(archivo)
        ruta = os.path.join(entradas, nombre)
        if not os.path.isfile(ruta):
            raise RuntimeError("No se encontró el archivo «%s»" % nombre)
        ext = os.path.splitext(nombre)[1].lower()
        antes = doc.page_count
        if ext == ".pdf":
            origen = fitz.open(ruta)
            try:
                doc.insert_pdf(origen)
            finally:
                origen.close()
            tipo = "pdf"
        elif ext in EXT_IMAGEN:
            imagenes = cargar_imagenes(ruta)
            if not imagenes:
                raise RuntimeError("La imagen «%s» no tiene contenido" % nombre)
            for img in imagenes:
                insertar_imagen(doc, img)
            tipo = "imagen"
        elif ext in EXT_WORD:
            with tempfile.TemporaryDirectory(dir=carpeta, prefix="word_") as tmp:
                pdf_tmp = word_a_pdf(ruta, tmp)
                origen = fitz.open(pdf_tmp)
                try:
                    doc.insert_pdf(origen)
                finally:
                    origen.close()
            tipo = "word"
        else:
            raise RuntimeError("Formato no soportado: «%s»" % nombre)
        paginas = doc.page_count - antes
        if paginas <= 0:
            raise RuntimeError("El archivo «%s» no produjo páginas" % nombre)
        for k in range(paginas):
            origenes.append({
                "n": antes + k + 1,
                "archivo": nombre,
                "nombre": nombres.get(nombre, nombre),
                "tipo": tipo,
                "pagina_origen": k + 1,
                "paginas_origen": paginas,
                "indice": indice,
            })
    if doc.page_count == 0:
        doc.close()
        raise RuntimeError("No se pudo construir el PDF con los archivos enviados")
    destino = os.path.join(carpeta, "original.pdf")
    temporal = os.path.join(carpeta, "original.nuevo.pdf")
    doc.save(temporal)
    doc.close()
    os.replace(temporal, destino)
    escribir_json(os.path.join(carpeta, "origenes.json"), origenes)
    return origenes


def vectorizar_imagenes(carpeta: str, salida: str, origenes: List[dict]) -> List[dict]:
    """Convierte cada imagen de entrada en un SVG vectorial B/N con potrace."""
    potrace = shutil.which("potrace")
    if not potrace or not origenes:
        return []
    resultado, vistos = [], set()
    for o in origenes:
        if o.get("tipo") != "imagen":
            continue
        clave = (o["archivo"], o.get("pagina_origen", 1))
        if clave in vistos:
            continue
        vistos.add(clave)
        ruta = os.path.join(carpeta, "entradas", o["archivo"])
        if not os.path.isfile(ruta):
            continue
        try:
            imagenes = cargar_imagenes(ruta)
            k = o.get("pagina_origen", 1) - 1
            if k < 0 or k >= len(imagenes):
                continue
            gris = ImageOps.autocontrast(imagenes[k].convert("L"))
            binaria = gris.point(lambda p: 255 if p > 160 else 0).convert("1")
            sufijo = "" if len(imagenes) == 1 else "_p%d" % (k + 1)
            archivo_svg = "vector_%s%s.svg" % (slug(o["archivo"]), sufijo)
            with tempfile.TemporaryDirectory() as tmp:
                bmp = os.path.join(tmp, "entrada.bmp")
                binaria.save(bmp, format="BMP")
                subprocess.run(
                    [potrace, "-s", "-o", os.path.join(salida, archivo_svg), bmp],
                    check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180,
                )
            resultado.append({
                "nombre": o.get("nombre", o["archivo"]),
                "pagina": k + 1,
                "archivo": archivo_svg,
            })
        except Exception:  # noqa
            traceback.print_exc()
    return resultado


def armar_texto(d, umbral=UMBRAL_PALABRA):
    """Del resultado de Tesseract saca líneas, párrafos y confianza media.
    Las palabras de baja confianza se sustituyen por «ilegible» (una sola vez por tramo)."""
    lineas = {}
    confs = []
    for i, t in enumerate(d["text"]):
        t = t.strip()
        if not t:
            continue
        c = float(d["conf"][i])
        if c >= 0:
            confs.append(c)
        lineas.setdefault((d["block_num"][i], d["par_num"][i], d["line_num"][i]), []).append((t, c))
    por_parrafo = {}
    for (b, p, _), palabras in lineas.items():
        out = []
        for t, c in palabras:
            if c < umbral:
                if re.search(r"\w", t) and (not out or out[-1] != "ilegible"):
                    out.append("ilegible")
            else:
                out.append(t)
        if out:
            por_parrafo.setdefault((b, p), []).append(" ".join(out))
    lineas_txt = [l for ls in por_parrafo.values() for l in ls]
    parrafos = [" ".join(ls) for ls in por_parrafo.values()]
    return lineas_txt, parrafos, (sum(confs) / len(confs) if confs else 0.0)


def ocr_imagen(img_bgr):
    """OCR de una página. Devuelve (líneas, párrafos, confianza, líneas_sin_filtrar).
    Las líneas sin filtrar conservan también las palabras de baja confianza: los títulos
    grandes o decorados suelen leerse con poca confianza y no deben perderse para detectarlos."""
    gris = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    d = pytesseract.image_to_data(Image.fromarray(gris), lang="spa", output_type=Output.DICT)
    lineas, parrafos, conf = armar_texto(d)
    sin_filtrar, _, _ = armar_texto(d, umbral=-1)
    return lineas, parrafos, conf, sin_filtrar


def orientar(img_bgr):
    """Detecta si la hoja está girada y la endereza (solo se usa si el OCR salió mal)."""
    try:
        gris = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        osd = pytesseract.image_to_osd(Image.fromarray(gris), output_type=Output.DICT)
        if float(osd.get("orientation_conf", 0)) >= 2.0:
            giro = int(osd.get("rotate", 0))
            if giro == 90:
                return cv2.rotate(img_bgr, cv2.ROTATE_90_CLOCKWISE)
            if giro == 180:
                return cv2.rotate(img_bgr, cv2.ROTATE_180)
            if giro == 270:
                return cv2.rotate(img_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
    except Exception:
        pass
    return img_bgr


# ------------------------------------------------------------------ cargos
CARGOS = [
    "Presidente del Directorio", "Vicepresidente", "Presidente", "Presidenta",
    "Secretario General", "Secretaria General", "Secretario", "Secretaria",
    "Tesorero", "Tesorera", "Vocal",
    "Notario de Fe Pública", "Notaria de Fe Pública", "Notario", "Notaria",
    "Subdirector", "Subdirectora", "Director", "Directora", "Jefe", "Jefa",
    "Registrador", "Registradora", "Alcalde", "Alcaldesa", "Gobernador", "Gobernadora",
    "Viceministro", "Viceministra", "Ministro", "Ministra", "Representante Legal",
    "Fiscal", "Juez", "Jueza", "Coordinador", "Coordinadora", "Responsable",
    "Asesor Legal", "Asesora Legal", "Abogado", "Abogada", "Oficial Mayor", "Concejal",
    "Dirigente", "Delegado", "Delegada", "Apoderado", "Apoderada",
]
_CARGOS_ORD = sorted(CARGOS, key=len, reverse=True)
RE_CARGO = re.compile(
    r"\b(" + "|".join(re.escape(sin_acentos(c).lower()) for c in _CARGOS_ORD) + r")\b"
)
_CARGO_CANON = {sin_acentos(c).lower(): c for c in CARGOS}
RE_NOMBRE = re.compile(
    r"^[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ.]+(?: (?:de|del|la|los|las|y|[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ.]*)){1,5}$"
)


def extraer_cargos(lineas):
    """Busca cargos en las líneas. Si la línea es solo el cargo y la anterior parece un
    nombre (bloque de firma), devuelve «Nombre (Cargo)»."""
    res = []
    for i, linea in enumerate(lineas):
        ln = sin_acentos(linea).lower()
        halladas = [m.group(1) for m in RE_CARGO.finditer(ln)]
        if not halladas:
            continue
        sola = len(re.sub(r"[^a-z ]", "", ln).strip()) <= len(halladas[0]) + 3
        previa = lineas[i - 1].strip() if i > 0 else ""
        for h in halladas:
            cargo = _CARGO_CANON[h]
            if sola and RE_NOMBRE.match(previa) and not re.search(r"\d", previa) and len(previa) < 60:
                item = "%s (%s)" % (previa, cargo)
            else:
                item = cargo
            if item not in res:
                res.append(item)
    return res


# ------------------------------------------------------------------ sellos
def _palabras_sello(d):
    lineas, confs = {}, []
    for i, t in enumerate(d["text"]):
        t = t.strip()
        c = float(d["conf"][i])
        if not t or c < UMBRAL_SELLO or len(re.findall(r"\w", t)) < 2:
            continue
        confs.append(c)
        lineas.setdefault((d["block_num"][i], d["par_num"][i], d["line_num"][i]), []).append(t)
    texto = [" ".join(v) for v in lineas.values()]
    return texto, (sum(confs) / len(confs) if confs else 0.0)


def leer_sello(recorte):
    gris = cv2.cvtColor(recorte, cv2.COLOR_BGR2GRAY)
    gris = cv2.resize(gris, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    gris = cv2.normalize(gris, None, 0, 255, cv2.NORM_MINMAX)
    mejor, mejor_puntaje = [], 0.0
    for giro in (None, cv2.ROTATE_180, cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_90_COUNTERCLOCKWISE):
        g = gris if giro is None else cv2.rotate(gris, giro)
        d = pytesseract.image_to_data(Image.fromarray(g), lang="spa", config="--psm 6", output_type=Output.DICT)
        lineas, conf = _palabras_sello(d)
        letras = len(re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ0-9]", " ".join(lineas)))
        puntaje = conf * letras
        if puntaje > mejor_puntaje:
            mejor, mejor_puntaje = lineas, puntaje
    letras = len(re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ0-9]", " ".join(mejor)))
    if letras < 8:
        return {"texto": "", "lineas": [], "legible": False}
    return {"texto": " ".join(mejor), "lineas": mejor, "legible": True}


def detectar_sellos(img):
    """Los sellos suelen ser manchas grandes de tinta de color (azul, violeta, roja).
    Se aíslan por color, se recortan y se leen con OCR. Si no se leen, quedan «ilegible».
    Limitación: sellos de tinta negra no se detectan con este método."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    tinta = ((hsv[:, :, 1] > 50) & (hsv[:, :, 2] > 40)).astype(np.uint8) * 255
    if tinta.mean() / 255.0 > 0.30:  # papel de color: no se puede aislar la tinta
        return []
    unido = cv2.morphologyEx(tinta, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31)))
    contornos, _ = cv2.findContours(unido, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    alto, ancho = img.shape[:2]
    sellos = []
    for c in sorted(contornos, key=cv2.contourArea, reverse=True)[:6]:
        x, y, w, h = cv2.boundingRect(c)
        if w < 0.10 * ancho or h < 0.045 * alto:
            continue
        if w > 0.7 * ancho and h > 0.7 * alto:
            continue
        if tinta[y:y + h, x:x + w].mean() / 255.0 < 0.015:
            continue
        s = leer_sello(img[y:y + h, x:x + w])
        s["pos"] = [int(x), int(y), int(w), int(h)]
        sellos.append(s)
    sellos.sort(key=lambda s: (s["pos"][1], s["pos"][0]))
    return sellos


# ------------------------------------------------------------------ títulos y documentos
# Palabras que suelen abrir un documento (sin tildes, en mayúsculas). Agrega las que usen los tuyos.
PALABRAS_TITULO = [
    "ACTA", "ACUERDO", "ADENDA", "ANEXO", "AUTO", "AUTORIZACION", "BALANCE", "BOLETA", "CARTA",
    "CEDULA", "CERTIFICACION", "CERTIFICADO", "CITACION", "COMPROBANTE", "CONSTANCIA", "CONTRATO",
    "CONVENIO", "CONVOCATORIA", "CURRICULUM", "DECLARACION", "DECLARATORIA", "DEMANDA", "DILIGENCIA",
    "DIPLOMA", "EDICTO", "ESCRITURA", "ESTATUTO", "ESTATUTOS", "FACTURA", "FORMULARIO", "INFORME",
    "LEGALIZACION", "LICENCIA", "LISTA", "MANDATO", "MATRICULA", "MEMORANDUM", "MEMORIAL", "MINUTA",
    "NIT", "NOMINA", "NOTA", "NOTIFICACION", "OFICIO", "PASAPORTE", "PERSONERIA", "PLANILLA", "PODER",
    "PROTOCOLIZACION", "RECIBO", "REGLAMENTO", "RESOLUCION", "SENTENCIA", "SOLICITUD", "TESTIMONIO",
]
_KW = set(PALABRAS_TITULO)
_KW_LARGAS = [k for k in PALABRAS_TITULO if len(k) >= 7]
# Verbos que se parecen a un título pero aparecen dentro del cuerpo («EL NOTARIO CERTIFICA»).
_NO_TITULO = {"CERTIFICA", "AUTORIZA", "INFORMA", "DECLARA", "NOTIFICA", "CITA", "CONVOCA", "LEGALIZA", "OTORGA"}
RE_TITULO = re.compile(r"\b(" + "|".join(PALABRAS_TITULO) + r")\b")  # se conserva por compatibilidad


def _palabras(linea: str) -> List[str]:
    return re.findall(r"[A-Z]+", sin_acentos(linea).upper())


def _es_palabra_titulo(w: str) -> bool:
    """Coincidencia exacta, o aproximada si el OCR cambió alguna letra (CERTIFICAD0, CERT1FICADO…)."""
    if w in _NO_TITULO:
        return False
    if w in _KW:
        return True
    return len(w) >= 7 and bool(get_close_matches(w, _KW_LARGAS, n=1, cutoff=0.88))


def es_titulo(linea: str) -> bool:
    s = linea.strip()
    letras = [c for c in s if c.isalpha()]
    if len(letras) < 4 or len(s) > 120:
        return False
    return sum(c.isupper() for c in letras) / len(letras) >= 0.8


def titulo_de(lineas) -> Optional[str]:
    """Busca el título en las primeras líneas de la página.
    * En MAYÚSCULAS: vale cualquier línea de las primeras 12 que contenga una palabra de título
      (así se salta los membretes tipo «ESTADO PLURINACIONAL DE BOLIVIA»).
    * En minúsculas/mixto («Poder Especial»): solo en las 6 primeras líneas, corta, sin punto final
      y empezando con la palabra de título, para no confundirla con el texto del cuerpo."""
    for i, l in enumerate(lineas[:12]):
        palabras = _palabras(l)
        if not any(_es_palabra_titulo(w) for w in palabras):
            continue
        t = re.sub(r"\s+", " ", l.strip(" .:-_"))
        if es_titulo(l):
            return t.capitalize()
        bruta = l.strip()
        if (i < 6 and len(bruta) <= 60 and len(bruta.split()) <= 8
                and not bruta.endswith((".", ",", ";")) and palabras and _es_palabra_titulo(palabras[0])):
            return t.capitalize()
    return None


RE_PAG1 = re.compile(r"(?:\bp[aá]g(?:ina)?\.?|\bhoja|\bfolio)\s*(?:n[.º°o]*\s*)?0?1\s*(?:de|/)\s*\d{1,3}\b", re.I)
RE_PAG1_SOLA = re.compile(r"^\W*0?1\s*(?:de|/)\s*\d{1,3}\W*$", re.I)


def es_pagina_uno(lineas) -> bool:
    """¿La página dice «Página 1 de N», «Hoja 1/N» o similar? Marca el inicio de un documento."""
    for l in list(lineas[:5]) + list(lineas[-5:]):
        if RE_PAG1.search(l) or RE_PAG1_SOLA.match(l.strip()):
            return True
    return False


def tinta_central(img) -> float:
    """Fracción de píxeles oscuros en el centro de la hoja (ignora los bordes del escáner)."""
    gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gris.shape
    centro = gris[int(h * 0.08):int(h * 0.92), int(w * 0.08):int(w * 0.92)]
    return float(np.count_nonzero(centro < 160)) / max(1, centro.size)


def tapar_sellos(img, sellos):
    """Copia de la página con los sellos pintados de blanco, para que su texto no se mezcle con el cuerpo."""
    limpia = img.copy()
    for s in sellos:
        x, y, w, h = s["pos"]
        cv2.rectangle(limpia, (max(0, x - 12), max(0, y - 12)), (x + w + 12, y + h + 12), (255, 255, 255), -1)
    return limpia


def analizar_pagina(pagina, n):
    img = renderizar(pagina)
    sellos = detectar_sellos(img)
    nativo = texto_nativo(pagina)
    if nativo:
        lineas, parrafos, conf = nativo
        lineas_titulo = lineas
    else:
        base = tapar_sellos(img, sellos)
        lineas, parrafos, conf, lineas_titulo = ocr_imagen(base)
        if conf < 50:  # puede estar girada
            base2 = orientar(base)
            if base2 is not base:
                l2, p2, c2, t2 = ocr_imagen(base2)
                if c2 > conf:
                    lineas, parrafos, conf, lineas_titulo = l2, p2, c2, t2
    cargos = extraer_cargos(lineas)
    for s in sellos:
        for c in extraer_cargos(s["lineas"]):
            if c not in cargos:
                cargos.append(c)
    cargos = [c for c in cargos if not any(c != o and c.lower() in o.lower() for o in cargos)]
    texto_total = " ".join(parrafos)
    titulo = titulo_de(lineas_titulo)
    if titulo is None and sellos and not nativo:
        # Un título de color (azul, rojo…) pudo borrarse junto con los sellos: se lee otra vez
        # el tercio superior de la hoja sin taparlos.
        arriba = img[: max(1, img.shape[0] // 3)]
        titulo = titulo_de(ocr_imagen(arriba)[3])
    letras = len(re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ0-9]", texto_total))
    tinta = tinta_central(img)
    return {
        "n": n,
        "lineas": lineas,
        "parrafos": parrafos,
        "conf": round(conf, 1),
        "sellos": sellos,
        "cargos": cargos,
        "titulo": titulo,
        "pag1": es_pagina_uno(lineas_titulo),
        "ancho": round(float(pagina.rect.width), 1),
        "alto": round(float(pagina.rect.height), 1),
        "tinta": round(tinta, 4),
        # Solo es «en blanco» si además no tiene nada impreso: una foto o una fotocopia sin texto
        # legible (cédula, plano…) NO es una hoja en blanco y no debe descartarse.
        "en_blanco": letras < 6 and not sellos and not titulo and tinta < 0.004,
    }


def _dims(p):
    a, b = p.get("ancho"), p.get("alto")
    if not a or not b:
        return None
    return tuple(sorted((float(a), float(b))))  # sin importar si la hoja está girada


def _tamano_distinto(p, q) -> bool:
    d1, d2 = _dims(p), _dims(q)
    if not d1 or not d2:
        return False
    return any(abs(x - y) / max(x, y) > 0.06 for x, y in zip(d1, d2))


def segmentar(paginas, origenes=None):
    """Propone los documentos. Una página abre un documento nuevo cuando:
      1. es la primera de un archivo subido;
      2. tiene un título (ACTA, CARTA, CERTIFICADO, PODER…);
      3. dice «Página 1 de N» (o «Hoja 1/N»);
      4. cambia el tamaño de la hoja respecto a la página anterior;
      5. viene después de una hoja realmente en blanco (que se descarta).
    El resto continúa el documento anterior. Cada documento guarda en «motivo» por qué se abrió."""
    inicios = {o["n"] for o in (origenes or []) if o.get("pagina_origen") == 1}
    docs, actual, anterior = [], None, None
    for p in paginas:
        if p["en_blanco"]:
            actual, anterior = None, None
            continue
        if p["titulo"]:
            motivo = "título"
        elif p["n"] in inicios:
            motivo = "archivo nuevo"
        elif actual is None:
            motivo = "inicio"
        elif p.get("pag1"):
            motivo = "página 1"
        elif anterior is not None and _tamano_distinto(p, anterior):
            motivo = "tamaño de hoja distinto"
        else:
            motivo = None
        if motivo:
            actual = {"nombre": p["titulo"] or "Documento %d" % (len(docs) + 1),
                      "desde": p["n"], "hasta": p["n"], "motivo": motivo}
            docs.append(actual)
        else:
            actual["hasta"] = p["n"]
        anterior = p
    if not docs and paginas:
        docs = [{"nombre": "Documento 1", "desde": 1, "hasta": len(paginas), "motivo": "inicio"}]
    return docs


# ------------------------------------------------------------------ puntuación del protocolo
ABREV = set(
    "sr sra sres srta dr dra lic ing arq art arts núm num av cap inc etc prof pdte dpto tel cel "
    "ref fdo vo bo cia ltda ud uds pág págs pag pags vol ed".split()
)
RE_INICIO_ORACION = re.compile(r"\s+[A-ZÁÉÍÓÚÑ¿¡\"“«(\d]")


def puntuar_parrafo(par: str) -> str:
    """Punto seguido -> «-»; punto y aparte (fin de párrafo) -> «.---».
    No toca decimales (1.500), abreviaturas (Sr., Art.), iniciales (J.) ni puntos suspensivos."""
    par = re.sub(r"\s+", " ", par).strip()
    res = list(par)
    for i, ch in enumerate(par):
        if ch != ".":
            continue
        antes, despues = par[:i], par[i + 1:]
        if despues.strip() == "":
            res[i] = ".---"
            continue
        if despues.startswith(".") or antes.endswith("."):
            continue
        if antes[-1:].isdigit() and despues[:1].isdigit():
            continue
        m = re.search(r"(\w+)$", antes)
        palabra = m.group(1) if m else ""
        if palabra.lower() in ABREV or (len(palabra) == 1 and palabra.isalpha() and palabra.isupper()):
            continue
        if RE_INICIO_ORACION.match(despues):
            res[i] = "-"
    return "".join(res)


def aplicar_puntuacion(parrafos: List[str]) -> str:
    return " ".join(p for p in (puntuar_parrafo(x) for x in parrafos) if p)


def construir_protocolo(docs, paginas) -> str:
    partes = ["PROTOCOLO"]
    for k, d in enumerate(docs, 1):
        trozo = paginas[d["desde"] - 1:d["hasta"]]
        parrafos, sellos, cargos = [], [], []
        for p in trozo:
            parrafos += p["parrafos"]
            sellos += [s["texto"] if s["legible"] else "ilegible" for s in p["sellos"]]
            for c in p["cargos"]:
                if c not in cargos:
                    cargos.append(c)
        texto = aplicar_puntuacion(parrafos) or "ilegible"
        partes.append(
            "DOCUMENTO %d (%s), páginas %d a %d: TEXTO: %s SELLOS: %s CARGOS: %s"
            % (k, d["nombre"], d["desde"], d["hasta"], texto,
               "; ".join(sellos) if sellos else "ninguno detectado",
               "; ".join(cargos) if cargos else "ninguno detectado")
        )
    return re.sub(r"\s+", " ", limpiar_control(" ".join(partes))).strip()


# ------------------------------------------------------------------ salida
def fijar_fuente(estilo, nombre=FUENTE):
    estilo.font.name = nombre
    rpr = estilo.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    for a in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rfonts.set(qn(a), nombre)


def guardar_docx(texto: str, ruta: str):
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.left_margin = sec.right_margin = sec.top_margin = sec.bottom_margin = Cm(2.5)
    fijar_fuente(doc.styles["Normal"])
    doc.styles["Normal"].font.size = Pt(12)
    doc.core_properties.title = "Protocolo"
    doc.add_paragraph(texto).alignment = WD_ALIGN_PARAGRAPH.JUSTIFY  # un solo párrafo
    doc.save(ruta)


def generar_salida(carpeta: str, docs, paginas, total: int):
    salida = os.path.join(carpeta, "salida")
    shutil.rmtree(salida, ignore_errors=True)
    os.makedirs(salida)
    try:
        origenes = leer_json(os.path.join(carpeta, "origenes.json"))
    except Exception:
        origenes = []
    por_pagina = {o["n"]: o for o in origenes}

    # Los PDFs se numeran por orden de páginas (estable aunque el Word se reordene).
    orden = sorted(range(len(docs)), key=lambda i: (docs[i]["desde"], docs[i]["hasta"]))
    numeros = {i: k for k, i in enumerate(orden, 1)}

    origen = fitz.open(os.path.join(carpeta, "original.pdf"))
    resultado_docs = []
    for i, d in enumerate(docs):
        archivo = "%02d_%s.pdf" % (numeros[i], slug(d["nombre"]))
        nuevo = fitz.open()
        nuevo.insert_pdf(origen, from_page=d["desde"] - 1, to_page=d["hasta"] - 1)
        nuevo.save(os.path.join(salida, archivo))
        nuevo.close()
        fuentes = []
        for n in range(d["desde"], d["hasta"] + 1):
            o = por_pagina.get(n)
            if o:
                nombre = o.get("nombre", o["archivo"])
                if nombre not in fuentes:
                    fuentes.append(nombre)
        resultado_docs.append({
            "id": i + 1,
            "nombre": d["nombre"],
            "desde": d["desde"],
            "hasta": d["hasta"],
            "archivo": archivo,
            "origen": fuentes,
            "motivo": d.get("motivo"),
        })
    origen.close()

    texto = construir_protocolo(docs, paginas)
    guardar_docx(texto, os.path.join(salida, "protocolo.docx"))

    vectorizados = vectorizar_imagenes(carpeta, salida, origenes)

    estado = {
        "estado": "listo",
        "total": total,
        "documentos": resultado_docs,
        "protocolo_docx": "protocolo.docx",
        "vectorizados": vectorizados,
        "origenes": origenes,
        "sellos_total": sum(len(p["sellos"]) for p in paginas),
        "sellos_ilegibles": sum(1 for p in paginas for s in p["sellos"] if not s["legible"]),
    }
    escribir_json(os.path.join(carpeta, "estado.json"), estado)
    return estado


# ------------------------------------------------------------------ trabajos
def procesar_trabajo(carpeta: str, archivos: Optional[List[str]] = None):
    estado_ruta = os.path.join(carpeta, "estado.json")
    try:
        if archivos:
            escribir_json(estado_ruta, {
                "estado": "procesando", "pagina": 0, "total": 0,
                "etapa": "Convirtiendo Word e imágenes y uniendo los archivos",
            })
            preparar_pdf(carpeta, archivos)
        try:
            origenes = leer_json(os.path.join(carpeta, "origenes.json"))
        except Exception:
            origenes = []
        pdf = fitz.open(os.path.join(carpeta, "original.pdf"))
        total = len(pdf)
        paginas_ruta = os.path.join(carpeta, "paginas.json")
        # Al agregar archivos a un trabajo existente se reutiliza el análisis de las
        # páginas ya procesadas y solo se hace OCR de las nuevas.
        try:
            paginas = leer_json(paginas_ruta)
            if not isinstance(paginas, list):
                paginas = []
        except Exception:
            paginas = []
        if len(paginas) > total:
            paginas = paginas[:total]
        for i in range(len(paginas), total):
            escribir_json(estado_ruta, {
                "estado": "procesando", "pagina": i + 1, "total": total,
                "etapa": "Leyendo la página %d de %d" % (i + 1, total),
            })
            paginas.append(analizar_pagina(pdf[i], i + 1))
        pdf.close()
        escribir_json(paginas_ruta, paginas)
        escribir_json(estado_ruta, {"estado": "procesando", "pagina": total, "total": total,
                                    "etapa": "Separando documentos y armando el protocolo"})
        generar_salida(carpeta, segmentar(paginas, origenes), paginas, total)
    except Exception as e:  # noqa
        traceback.print_exc()
        escribir_json(estado_ruta, {"estado": "error", "mensaje": "No se pudieron procesar los archivos: %s" % e})


class EntradaProcesar(BaseModel):
    dir: str
    archivos: List[str] = []


class DocumentoRango(BaseModel):
    nombre: str
    desde: int
    hasta: int


class EntradaDividir(BaseModel):
    dir: str
    documentos: List[DocumentoRango]


def validar_dir(d: str) -> str:
    d = os.path.abspath(d)
    if not os.path.isdir(d):
        raise HTTPException(400, "No existe el trabajo")
    if not os.path.isfile(os.path.join(d, "original.pdf")) and not os.path.isdir(os.path.join(d, "entradas")):
        raise HTTPException(400, "No existe el trabajo")
    return d


def validar_archivos(carpeta: str, archivos: List[str]) -> List[str]:
    base = os.path.realpath(os.path.join(carpeta, "entradas"))
    limpios = []
    for a in archivos:
        nombre = os.path.basename(a)
        ruta = os.path.realpath(os.path.join(base, nombre))
        if os.path.dirname(ruta) != base or not os.path.isfile(ruta):
            raise HTTPException(400, "Archivo no encontrado: %s" % nombre)
        limpios.append(nombre)
    return limpios


@app.post("/procesar")
def procesar(e: EntradaProcesar, tareas: BackgroundTasks):
    carpeta = validar_dir(e.dir)
    archivos = validar_archivos(carpeta, e.archivos) if e.archivos else []
    tareas.add_task(procesar_trabajo, carpeta, archivos)
    return {"ok": True}


@app.post("/dividir")
def dividir(e: EntradaDividir):
    carpeta = validar_dir(e.dir)
    ruta = os.path.join(carpeta, "paginas.json")
    if not os.path.isfile(ruta):
        raise HTTPException(400, "Los archivos todavía no terminan de procesarse")
    paginas = leer_json(ruta)
    total = len(paginas)
    if not e.documentos:
        raise HTTPException(400, "Debe haber al menos un documento")
    docs = []
    for d in e.documentos:
        if not d.nombre.strip():
            raise HTTPException(400, "Todos los documentos necesitan un nombre")
        if not (1 <= d.desde <= d.hasta <= total):
            raise HTTPException(400, "Rango de páginas no válido para «%s»: el PDF tiene %d páginas" % (d.nombre, total))
        docs.append({"nombre": d.nombre.strip(), "desde": d.desde, "hasta": d.hasta})
    return generar_salida(carpeta, docs, paginas, total)


def parsear_paginas(texto: str, total: int) -> List[tuple]:
    """«3-7», «1, 4, 6-8», «5-» (hasta el final) o «-4» (desde el inicio) → [(desde, hasta), …]."""
    partes = [p.strip() for p in re.split(r"[;,]", texto or "") if p.strip()]
    if not partes:
        raise HTTPException(400, "Indica las páginas a cortar, por ejemplo 3-7")
    rangos = []
    for p in partes:
        m = re.fullmatch(r"(\d+)\s*[-–—]\s*(\d+)?|[-–—]\s*(\d+)|(\d+)", p)
        if not m:
            raise HTTPException(400, "No entiendo «%s». Usa por ejemplo 3-7 o 1,4,6-8" % p)
        if m.group(4):
            a = b = int(m.group(4))
        elif m.group(3):
            a, b = 1, int(m.group(3))
        else:
            a = int(m.group(1))
            b = int(m.group(2)) if m.group(2) else total
        if not (1 <= a <= b <= total):
            raise HTTPException(400, "El archivo tiene %d página(s); el rango «%s» no es válido" % (total, p))
        rangos.append((a, b))
    return rangos


class EntradaCortar(BaseModel):
    dir: str
    archivo: str
    paginas: str


@app.post("/cortar")
def cortar(e: EntradaCortar):
    """Corta las páginas indicadas de UN archivo (PDF, Word o imagen) y las deja en salida/corte.pdf.
    No hace OCR ni toca ningún trabajo: solo convierte a PDF y recorta."""
    carpeta = validar_dir(e.dir)
    archivos = validar_archivos(carpeta, [e.archivo])
    try:
        preparar_pdf(carpeta, archivos)  # deja el archivo convertido en original.pdf
    except RuntimeError as err:
        raise HTTPException(400, str(err))
    origen = fitz.open(os.path.join(carpeta, "original.pdf"))
    try:
        total = origen.page_count
        rangos = parsear_paginas(e.paginas, total)
        salida = os.path.join(carpeta, "salida")
        os.makedirs(salida, exist_ok=True)
        nuevo = fitz.open()
        for a, b in rangos:
            nuevo.insert_pdf(origen, from_page=a - 1, to_page=b - 1)
        nuevo.save(os.path.join(salida, "corte.pdf"))
        exportadas = nuevo.page_count
        nuevo.close()
    finally:
        origen.close()
    return {"archivo": "corte.pdf", "total": total, "paginas": exportadas}


@app.get("/salud")
def salud():
    return {"ok": True}
