import re

def format_paragraph(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if not text: return ""
    return text[:-1] + ".---" if text.endswith(".") else text + ".---"

def build_protocol(documents, pages):
    parts = []
    for number, document in enumerate(documents, 1):
        selected = [p for p in pages if document["start_page"] <= p["page"] <= document["end_page"]]
        paragraphs = []
        for page in selected:
            paragraphs.extend(x.strip() for x in re.split(r"\n\s*\n", page.get("text", "")) if x.strip())
        body = " ".join(format_paragraph(x) for x in paragraphs) if paragraphs else "ilegible.---"
        parts.append(f"DOCUMENTO {number} ({document['name']}), páginas {document['start_page']} a {document['end_page']}: {body}")
    return re.sub(r"\s+", " ", " ".join(parts)).strip()
