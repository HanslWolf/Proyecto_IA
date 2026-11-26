import { NotariaAPI } from "../api.js";

const CONFIG = {
  API_BASE: "http://127.0.0.1:8000",
  MAX_FILES: 30,
  MAX_FILE_MB: 30,
  MAX_TOTAL_MB: 150,
  EXTENSIONES_PERMITIDAS: [
    ".pdf", ".doc", ".docx",
    ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp",
  ],
};

const AREAS_ETIQUETAS = {
  contratos: "Área de Contratos",
  personeria_juridica: "Área de Verificación de Documentos de Personería Jurídica",
};

const api = new NotariaAPI(CONFIG.API_BASE);

const state = {
  archivos: [],
  jobId: null,
  resultado: null,
  ocupado: false,
};

const navButtons = document.querySelectorAll(".nav__btn");
const panels = document.querySelectorAll(".panel");
const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("file-input");
const btnSeleccionar = document.getElementById("btn-seleccionar");
const btnLimpiar = document.getElementById("btn-limpiar");
const btnProcesar = document.getElementById("btn-procesar");
const listaArchivos = document.getElementById("lista-archivos");
const contadorArchivos = document.getElementById("contador-archivos");
const alertasBox = document.getElementById("alertas");
const progresoCard = document.getElementById("progreso-card");
const estadoTitulo = document.getElementById("estado-titulo");
const estadoPorcentaje = document.getElementById("estado-porcentaje");
const barraProgreso = document.getElementById("barra-progreso");
const estadoDetalle = document.getElementById("estado-detalle");
const indicadorModo = document.getElementById("indicador-modo");

navButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    const targetId = btn.dataset.section;
    navButtons.forEach((b) => b.classList.toggle("is-active", b === btn));
    panels.forEach((p) => p.classList.toggle("is-visible", p.id === targetId));
  });
});

function mostrarAlerta(mensaje) {
  const div = document.createElement("div");
  div.className = "alerta";
  div.textContent = mensaje;
  alertasBox.appendChild(div);
}

function limpiarAlertas() {
  alertasBox.innerHTML = "";
}

function formatearTamano(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function obtenerExtension(nombre) {
  const idx = nombre.lastIndexOf(".");
  return idx >= 0 ? nombre.slice(idx).toLowerCase() : "";
}

function validarYAgregarArchivos(fileList) {
  if (state.ocupado) return;
  limpiarAlertas();
  const maxFileBytes = CONFIG.MAX_FILE_MB * 1024 * 1024;
  const maxTotalBytes = CONFIG.MAX_TOTAL_MB * 1024 * 1024;
  let totalActual = state.archivos.reduce((acc, f) => acc + f.size, 0);

  for (const file of Array.from(fileList)) {
    if (state.archivos.length >= CONFIG.MAX_FILES) {
      mostrarAlerta(`Máximo ${CONFIG.MAX_FILES} archivos por trabajo.`);
      break;
    }
    const ext = obtenerExtension(file.name);
    if (!CONFIG.EXTENSIONES_PERMITIDAS.includes(ext)) {
      mostrarAlerta(`Formato no permitido en «${file.name}».`);
      continue;
    }
    if (file.size === 0) {
      mostrarAlerta(`El archivo «${file.name}» está vacío.`);
      continue;
    }
    if (file.size > maxFileBytes) {
      mostrarAlerta(`«${file.name}» supera el límite de ${CONFIG.MAX_FILE_MB} MB por archivo.`);
      continue;
    }
    if (totalActual + file.size > maxTotalBytes) {
      mostrarAlerta(`Se superó el límite total de ${CONFIG.MAX_TOTAL_MB} MB por trabajo.`);
      continue;
    }
    state.archivos.push(file);
    totalActual += file.size;
  }
  renderizarArchivos();
}

function renderizarArchivos() {
  contadorArchivos.textContent = String(state.archivos.length);
  btnLimpiar.disabled = state.ocupado || state.archivos.length === 0;
  btnProcesar.disabled = state.ocupado || state.archivos.length === 0;

  if (state.archivos.length === 0) {
    listaArchivos.innerHTML = `<li class="file-list__empty">Aún no se han agregado archivos válidos.</li>`;
    return;
  }

  listaArchivos.innerHTML = "";
  state.archivos.forEach((file, index) => {
    const li = document.createElement("li");
    li.className = "file-item";

    const info = document.createElement("div");
    const nombre = document.createElement("strong");
    nombre.textContent = file.name;
    const meta = document.createElement("span");
    meta.className = "file-item__meta";
    meta.textContent = `(${formatearTamano(file.size)})`;
    info.append(nombre, meta);

    const btnEliminar = document.createElement("button");
    btnEliminar.disabled = state.ocupado;
    btnEliminar.type = "button";
    btnEliminar.className = "btn btn--ghost";
    btnEliminar.textContent = "Eliminar";
    btnEliminar.addEventListener("click", () => {
      state.archivos.splice(index, 1);
      renderizarArchivos();
    });

    li.append(info, btnEliminar);
    listaArchivos.appendChild(li);
  });
}

btnSeleccionar.addEventListener("click", (e) => {
  e.stopPropagation();
  fileInput.click();
});

dropzone.addEventListener("click", (e) => { if (e.target === dropzone || e.target.tagName === "P") fileInput.click(); });
dropzone.addEventListener("keydown", (e) => {
  if (e.target === dropzone && (e.key === "Enter" || e.key === " ")) {
    e.preventDefault();
    fileInput.click();
  }
});

fileInput.addEventListener("change", (e) => {
  if (e.target.files?.length) {
    validarYAgregarArchivos(e.target.files);
    fileInput.value = "";
  }
});

["dragenter", "dragover"].forEach((evt) => {
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropzone.classList.add("is-dragover");
  });
});

["dragleave", "drop"].forEach((evt) => {
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropzone.classList.remove("is-dragover");
  });
});

dropzone.addEventListener("drop", (e) => {
  if (e.dataTransfer?.files?.length) {
    validarYAgregarArchivos(e.dataTransfer.files);
  }
});

btnLimpiar.addEventListener("click", () => {
  state.archivos = [];
  limpiarAlertas();
  renderizarArchivos();
});

function obtenerAreaSeleccionada() {
  const checked = document.querySelector('input[name="area"]:checked');
  return checked ? checked.value : "contratos";
}

function actualizarProgresoUI({ porcentaje = 0, etapa = "Procesando...", completado = false }) {
  progresoCard.classList.remove("hidden");
  const pct = Math.max(0, Math.min(100, Math.round(porcentaje)));
  estadoTitulo.textContent = completado ? "Procesamiento completado" : "Procesando documentos...";
  estadoPorcentaje.textContent = `${pct}%`;
  barraProgreso.style.width = `${pct}%`;
  estadoDetalle.textContent = etapa;
}

function irAResultados() {
  navButtons.forEach((b) => b.classList.toggle("is-active", b.dataset.section === "panel-resultados"));
  panels.forEach((p) => p.classList.toggle("is-visible", p.id === "panel-resultados"));
}

function renderizarResultados(data, areaKey) {
  document.getElementById("resumen-trabajo").textContent =
    `Trabajo ${data.job_id || state.jobId || "demo"} — ${AREAS_ETIQUETAS[areaKey] || areaKey}`;

  document.getElementById("metricas-grid").classList.remove("hidden");
  document.getElementById("metric-area").textContent = AREAS_ETIQUETAS[areaKey] || areaKey;
  document.getElementById("metric-paginas").textContent = String(data.total_pages ?? 0);
  document.getElementById("metric-docs").textContent = String(data.documents?.length ?? 0);
  document.getElementById("metric-revision").textContent = data.requires_review ? "Sí" : "No";

  const protoBox = document.getElementById("protocolo-general-box");
  const protoTexto = document.getElementById("protocolo-texto");
  if (data.protocol) {
    protoBox.classList.remove("hidden");
    protoTexto.textContent = data.protocol;
  } else {
    protoBox.classList.add("hidden");
  }

  const accionesDescarga = document.getElementById("acciones-descarga");
  const linkProtocolo = document.getElementById("link-protocolo");
  if (data.protocol_url) {
    accionesDescarga.classList.remove("hidden");
    linkProtocolo.href = data.protocol_url.startsWith("http")
      ? data.protocol_url
      : `${CONFIG.API_BASE}${data.protocol_url}`;
  } else {
    accionesDescarga.classList.add("hidden");
  }

  const pagesByDoc = (doc) =>
    (data.pages || []).filter((p) => p.page >= doc.start_page && p.page <= doc.end_page);

  const contenedorDocs = document.getElementById("contenedor-documentos");
  contenedorDocs.innerHTML = "";

  (data.documents || []).forEach((doc, idx) => {
    const card = document.createElement("article");
    card.className = "doc-card";

    const head = document.createElement("div");
    head.className = "doc-card__head";

    const titulo = document.createElement("h3");
    titulo.className = "doc-card__title";
    titulo.textContent = `${idx + 1}. ${doc.name || `Documento ${idx + 1}`}`;

    const badges = document.createElement("div");
    const rango = document.createElement("span");
    rango.className = "badge";
    rango.textContent = `Páginas ${doc.start_page}–${doc.end_page}`;
    badges.appendChild(rango);

    const paginasDoc = pagesByDoc(doc);
    const necesitaRevision = paginasDoc.some((p) => p.requires_review);
    if (necesitaRevision) {
      const rev = document.createElement("span");
      rev.className = "badge badge--warn";
      rev.style.marginLeft = "0.35rem";
      rev.textContent = "Requiere revisión";
      badges.appendChild(rev);
    }

    head.append(titulo, badges);
    card.appendChild(head);

    if (paginasDoc.length) {
      for (const pagina of paginasDoc) {
        const detail = document.createElement("details");
        const label = document.createElement("summary");
        label.textContent = `Página ${pagina.page} · ${pagina.source_name ?? "Documento"} · ${pagina.engine}${pagina.requires_review ? " · Revisar" : ""}`;
        const lectura = document.createElement("div");
        lectura.className = "doc-card__protocolo";
        lectura.textContent = [pagina.text, pagina.warning, ...(pagina.stamps ?? []).map(s => "Posible sello: " + s.text)].filter(Boolean).join("\n");
        detail.append(label, lectura);
        card.appendChild(detail);
      }
    }

    if (doc.url) {
      const pie = document.createElement("div");
      pie.style.marginTop = "0.75rem";
      const enlace = document.createElement("a");
      enlace.className = "btn btn--secondary";
      enlace.href = doc.url.startsWith("http") ? doc.url : `${CONFIG.API_BASE}${doc.url}`;
      enlace.download = doc.file || `documento_${idx + 1}.pdf`;
      enlace.textContent = "Descargar PDF del documento";
      pie.appendChild(enlace);
      card.appendChild(pie);
    }

    contenedorDocs.appendChild(card);
  });

  document.getElementById("corte").classList.remove("hidden");
  renderizarEditorRangos(data.documents || [], areaKey);
}

function renderizarEditorRangos(documentos, areaKey) {
  const editor = document.getElementById("editor-rangos");
  const filas = document.getElementById("filas-rangos");
  if (!documentos.length) {
    editor.classList.add("hidden");
    return;
  }
  editor.classList.remove("hidden");
  filas.innerHTML = "";

  documentos.forEach((doc, idx) => {
    const row = document.createElement("div");
    row.className = "range-row";

    const inpNombre = document.createElement("input");
    inpNombre.type = "text";
    inpNombre.value = doc.name || `Documento ${idx + 1}`;
    inpNombre.dataset.role = "name";

    const inpDesde = document.createElement("input");
    inpDesde.type = "number";
    inpDesde.min = "1";
    inpDesde.value = doc.start_page;
    inpDesde.dataset.role = "start_page";

    const inpHasta = document.createElement("input");
    inpHasta.type = "number";
    inpHasta.min = "1";
    inpHasta.value = doc.end_page;
    inpHasta.dataset.role = "end_page";

    row.append(inpNombre, inpDesde, inpHasta);
    filas.appendChild(row);
  });

  document.getElementById("btn-redividir").onclick = async () => {
    const nuevosDocs = Array.from(filas.querySelectorAll(".range-row")).map((row, idx) => ({
      name: row.querySelector('[data-role="name"]').value.trim() || `Documento ${idx + 1}`,
      start_page: Number(row.querySelector('[data-role="start_page"]').value),
      end_page: Number(row.querySelector('[data-role="end_page"]').value),
    }));

    const job = state.resultado.job_id;
    const alerta = document.getElementById("alerta-resultados");
    alerta.textContent = "";
    const boton = document.getElementById("btn-redividir");
    boton.disabled = true;
    try {
      const split = await api.dividir(job, nuevosDocs);
      if (state.resultado?.job_id !== job) return;
      state.resultado = {...state.resultado, documents: split.documents};
      renderizarResultados(state.resultado, areaKey);
    } catch (err) {
      if (state.resultado?.job_id === job) alerta.textContent = err.message;
    } finally { boton.disabled = false; }
  };
}

document.getElementById("btn-corte").onclick = async (event) => {
  const boton = event.currentTarget;
  const job = state.resultado.job_id;
  const link = document.getElementById("descargar-corte");
  const alerta = document.getElementById("alerta-resultados");
  link.classList.add("hidden");
  alerta.textContent = "";
  boton.disabled = true;
  try {
    const {url} = await api.cortar(job, document.getElementById("rango-corte").value);
    if (state.resultado?.job_id === job) {
      link.href = api.baseURL + url;
      link.classList.remove("hidden");
    }
  } catch (err) {
    if (state.resultado?.job_id === job) alerta.textContent = err.message;
  } finally { boton.disabled = false; }
};

btnProcesar.addEventListener("click", async () => {
  if (state.ocupado || !state.archivos.length) return;
  limpiarAlertas();
  state.ocupado = true;
  const area = obtenerAreaSeleccionada();
  renderizarArchivos();
  try {
    actualizarProgresoUI({ etapa: "Enviando archivos..." });
    const {job_id} = await api.procesar(state.archivos, area);
    state.jobId = job_id;
    while (true) {
      const trabajo = await api.estado(job_id);
      if (trabajo.status === "failed") throw new Error(trabajo.error);
      if (trabajo.status === "completed") break;
      actualizarProgresoUI({
        porcentaje: trabajo.total_pages ? 100 * trabajo.processed_pages / trabajo.total_pages : 0,
        etapa: trabajo.total_pages ? `Páginas procesadas: ${trabajo.processed_pages}/${trabajo.total_pages}` : "En cola o preparando el documento...",
      });
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    const data = await api.resultado(job_id);
    state.resultado = data;
    document.getElementById("descargar-corte").classList.add("hidden");
    document.getElementById("alerta-resultados").textContent = "";
    document.getElementById("rango-corte").value = "";
    renderizarResultados(data, data.area ?? area);
    actualizarProgresoUI({ porcentaje: 100, etapa: "Listo para revisar.", completado: true });
    irAResultados();
  } catch (err) {
    estadoTitulo.textContent = "Procesamiento interrumpido";
    estadoDetalle.textContent = err.message;
    mostrarAlerta(err.message);
  } finally {
    state.ocupado = false;
    renderizarArchivos();
  }
});

api.request("/salud").then(() => indicadorModo.textContent = "API disponible")
  .catch(() => indicadorModo.textContent = "API sin conexión");
renderizarArchivos();
