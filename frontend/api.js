export class NotariaAPI {
  constructor(baseURL = "http://127.0.0.1:8000") {
    this.baseURL = baseURL.replace(/\/$/, "");
  }

  async request(path, options = {}) {
    const response = await fetch(this.baseURL + path, options);
    const data = await response.json();
    if (!response.ok) {
      const detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
      throw new Error(`HTTP ${response.status}: ${detail}`);
    }
    return data;
  }

  procesar(files) {
    const body = new FormData();
    for (const file of files) body.append("files", file);
    return this.request("/procesar", {method: "POST", body});
  }

  estado(id) { return this.request(`/trabajos/${id}`); }
  resultado(id) { return this.request(`/trabajos/${id}/resultado`); }
  cortar(job_id, pages) { return this.postJSON("/cortar", {job_id, pages}); }
  dividir(job_id, documents) { return this.postJSON("/dividir", {job_id, documents}); }

  postJSON(path, payload) {
    return this.request(path, {method: "POST", headers: {"Content-Type": "application/json"},
                               body: JSON.stringify(payload)});
  }
}
