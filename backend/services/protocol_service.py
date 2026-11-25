import re
from docx import Document

# Abreviaturas frecuentes, iniciales y puntos dentro de números o direcciones.
ABBREVIATION = re.compile(r"(?:\b(?:bs|sr|sra|srta|dr|dra|lic|ing|art|arts|núm|nro|no|av|pág|inc|ref|etc))\.$", re.I)
SENTENCE_DOT = re.compile(r"(?<!\.)\.(?!\.)(?=\s+\S)")


def format_paragraph(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    def replace(match):
        prefix = text[:match.end()]
        initial = re.search(r"[A-ZÁÉÍÓÚÑ]\.$", prefix)
        return "." if initial or ABBREVIATION.search(prefix) else "-"
    text = SENTENCE_DOT.sub(replace, text)
    return (text[:-1] if text.endswith(".") and not text.endswith("...") else text) + ".---"


def build_protocol(documents, pages):
    by_number = {page["page"]: page for page in pages}
    parts = []
    for document in documents:
        for number in range(document["start_page"], document["end_page"] + 1):
            text = by_number[number]["text"].strip() or "ilegible"
            parts.extend(format_paragraph(p) for p in re.split(r"\n\s*\n", text) if p.strip())
    return " ".join(parts)


def save_protocol(text, path):
    document = Document()
    document.add_paragraph(text)
    document.save(path)
