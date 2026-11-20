"""Install pinned public Whisper weights; never run inference or call a paid API."""
import hashlib
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path

REVISION = "536b0662742c02347bc0e980a01041f333bce120"
FILES = {'config.json': 'b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828', 'model.bin': '3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671', 'tokenizer.json': 'fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab', 'vocabulary.txt': '34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913'}


def install():
    # Offline Korean/English OCR. Runtime never downloads weights or calls a model API.
    ocr_ready = False
    if shutil.which('tesseract'):
        probe = subprocess.run(['tesseract', '--list-langs'], capture_output=True, text=True, timeout=15)
        ocr_ready = probe.returncode == 0 and {'kor', 'eng'} <= set(probe.stdout.splitlines())
    if not ocr_ready:
        env = dict(os.environ, DEBIAN_FRONTEND='noninteractive')
        subprocess.run(['apt-get', 'update'], env=env, check=True, timeout=300)
        subprocess.run(['apt-get', 'install', '-y', '--no-install-recommends',
                        'tesseract-ocr', 'tesseract-ocr-kor', 'tesseract-ocr-eng'],
                       env=env, check=True, timeout=600)
    # Native PPT candidates need deterministic slide rasterization on the worker.
    # Runtime conversion still uses the existing bounded adapter and fresh gates.
    if any(shutil.which(name) is None for name in ("soffice", "pdftoppm", "pdftotext")):
        env = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
        subprocess.run(["apt-get", "update"], env=env, check=True, timeout=300)
        subprocess.run(["apt-get", "install", "-y", "--no-install-recommends",
                        "libreoffice-impress", "poppler-utils", "fonts-noto-cjk"],
                       env=env, check=True, timeout=600)
    root = Path("/var/lib/lerny-worker/models/faster-whisper-small")
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o755)
    for name, expected in FILES.items():
        target = root / name
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() == expected:
                continue
            raise RuntimeError("Existing model differs; explicit replacement required")
        temporary = root / (name + ".part")
        sha = hashlib.sha256()
        url = "https://huggingface.co/Systran/faster-whisper-small/resolve/" + REVISION + "/" + name
        with urllib.request.urlopen(url, timeout=90) as response, temporary.open("wb") as output:
            while block := response.read(1024 * 1024):
                sha.update(block)
                output.write(block)
        if sha.hexdigest() != expected:
            temporary.unlink()
            raise RuntimeError("Model checksum mismatch")
        temporary.chmod(0o644)
        temporary.replace(target)
    print("Pinned Whisper weights ready; no model inference performed", flush=True)


if __name__ == "__main__":
    install()
