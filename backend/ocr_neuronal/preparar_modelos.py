"""Preparar los pesos oficiales para la demostración local en CPU."""
from hashlib import file_digest
from pathlib import Path
from shutil import copyfileobj
from tarfile import open as open_tar
from tempfile import TemporaryDirectory
from urllib.request import urlopen

MODELS = {
    "PP-OCRv5_mobile_det": "50446e5d01ac2a73d5319c89513281f6578414c888c602f9af13f93feefffc58",
    "latin_PP-OCRv5_mobile_rec": "b23105a6a1ea38e32a97c5a0ddc7e8a9bbf541d8e47421e2c99e9ccabe29509c",
    "PP-LCNet_x1_0_textline_ori": "6171f69605215a85624d650e9079fa45f7c3eaf944296181bcc5395bf3ddc7f6",
}
BASE = "https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/"
FILES = ("inference.json", "inference.pdiparams", "inference.yml")


def prepare(root):
    root.mkdir(parents=True, exist_ok=True)
    for name, digest in MODELS.items():
        print(f"Preparando {name}...", flush=True)
        with TemporaryDirectory(dir=root) as scratch:
            archive = Path(scratch) / "modelo.tar"
            with urlopen(BASE + name + "_infer.tar", timeout=120) as remote, archive.open("wb") as output:
                copyfileobj(remote, output)
            with archive.open("rb") as stream:
                if file_digest(stream, "sha256").hexdigest() != digest:
                    raise RuntimeError(f"El SHA-256 de {name} no coincide con el modelo probado")
            with open_tar(archive) as bundle:
                for filename in FILES:
                    member = bundle.getmember(f"{name}_infer/{filename}")
                    if not member.isfile():
                        raise ValueError(f"Archivo de modelo inválido: {filename}")
                    with bundle.extractfile(member) as source, (Path(scratch)/filename).open("wb") as target:
                        copyfileobj(source, target)
            destination = root / name
            destination.mkdir(exist_ok=True)
            for filename in FILES:
                (Path(scratch)/filename).replace(destination/filename)
    print(f"Modelos preparados en {root}")


if __name__ == "__main__":
    prepare(Path(__file__).resolve().parents[1] / "modelos")
