"""Download official Windows runtimes into the external development directory."""
import concurrent.futures
import hashlib
import os
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(os.environ.get('LERNY_RUNTIME_ROOT', Path.home() / 'LernyData'))


def install(name, url, checksum=None):
    (ROOT / 'cache').mkdir(parents=True, exist_ok=True)
    archive = ROOT / 'cache' / (name + '.zip')
    target = ROOT / 'tools' / name
    if not archive.exists():
        partial = archive.with_suffix('.partial')
        print('Downloading', name, flush=True)
        urllib.request.urlretrieve(url, partial)
        partial.replace(archive)
    digest = hashlib.file_digest(archive.open('rb'), 'sha256').hexdigest()
    if checksum and digest != checksum:
        raise RuntimeError(f'{name}: checksum mismatch')
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for entry in z.infolist():
            if not (target / entry.filename).resolve().is_relative_to(target.resolve()):
                raise RuntimeError('Invalid archive path')
        z.extractall(target)
    print(name, 'installed; SHA256', digest, flush=True)


if __name__ == '__main__':
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(install, 'postgresql-17',
                        'https://sbp.enterprisedb.com/getfile.jsp?fileid=1260616'),
            pool.submit(install, 'ollama-0.40.2',
                        'https://github.com/ollama/ollama/releases/download/v0.40.2/ollama-windows-amd64.zip',
                        'e29ad1d5063dd4b54b2492d9b00adab2cff9621bfa654b6c92aa8d6f1fdfe7fc'),
        ]
        for future in futures:
            future.result()
