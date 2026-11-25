import re
TITLES = {"ACTA", "CONTRATO", "CONVENIO", "PODER", "ESCRITURA", "TESTIMONIO", "PERSONERIA", "PERSONERÍA", "CERTIFICADO", "RESOLUCION", "RESOLUCIÓN", "ESTATUTO", "MINUTA", "DECLARACION", "DECLARACIÓN", "SOLICITUD"}

def suggest_segments(pages):
    documents, current = [], None
    for page in pages:
        title = None
        for line in page.get("lines", [])[:12]:
            words = set(re.sub(r"[^A-ZÁÉÍÓÚÑ ]", " ", line.upper()).split())
            match = next((word for word in TITLES if word in words), None)
            letters = [c for c in line if c.isalpha()]
            if match and letters and sum(c.isupper() for c in letters) / len(letters) >= .75:
                title = line.strip()[:100]; break
        if current is None or title:
            current = {"name": title or f"Documento {len(documents)+1}", "start_page": page["page"], "end_page": page["page"]}
            documents.append(current)
        else: current["end_page"] = page["page"]
    return documents
