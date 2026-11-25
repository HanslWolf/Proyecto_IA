import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


def write_json(path: Path, value):
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        try:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
        except BaseException:
            stream.close()
            temp.unlink(missing_ok=True)
            raise
    os.replace(temp, path)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))
