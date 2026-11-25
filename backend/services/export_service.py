import re
import shutil
import uuid
from threading import Lock
import pymupdf as fitz
from utils.storage import read_json, write_json

_publish_lock = Lock()


def parse_ranges(value: str, total: int):
    result = []
    for token in value.split(","):
        item = token.strip()
        if not item:
            continue
        if re.fullmatch(r"\d+", item):
            start = end = int(item)
        elif re.fullmatch(r"\d*\s*-\s*\d*", item):
            a, b = item.split("-")
            start = int(a.strip() or 1)
            end = int(b.strip() or total)
        else:
            raise ValueError(f"Rango inválido: {item}")
        if not 1 <= start <= end <= total:
            raise ValueError(f"Rango inválido: {item}")
        result.append((start, end))
    if not result:
        raise ValueError("Indique páginas, por ejemplo 1,3,6-8")
    return result


def export(folder, specifications):
    if sum(b-a+1 for _, ranges in specifications for a,b in ranges) > 2000:
        raise ValueError("Máximo 2000 páginas por exportación")
    version = uuid.uuid4().hex
    directory = folder / "output" / version
    directory.mkdir(parents=True)
    try:
        with fitz.open(folder / "original.pdf") as source:
            for filename, ranges in specifications:
                with fitz.open() as part:
                    for start, end in ranges:
                        part.insert_pdf(source, from_page=start-1, to_page=end-1)
                    part.save(directory / filename)
        with _publish_lock:
            registry = folder / "exports.json"
            aliases = read_json(registry) if registry.exists() else {}
            aliases.update({filename: version for filename, _ in specifications})
            write_json(registry, aliases)
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    return version
