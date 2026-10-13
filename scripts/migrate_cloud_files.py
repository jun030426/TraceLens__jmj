"""Copy original files after an optional DB data import; never delete local files."""

import argparse
import hashlib
from pathlib import Path

from prepare_cloud import load_environment


def migrate(config_path, source_root):
    load_environment(config_path)
    from lerny import storage
    from lerny.db import engine
    from lerny.models import MaterialVersion
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    root = Path(source_root).resolve(strict=True)
    copied, verified = 0, 0
    with Session(engine()) as session:
        sources = session.execute(
            select(MaterialVersion.object_key, MaterialVersion.sha256).distinct()
        ).all()
    for key, sha in sources:
        source = (root / key).resolve()
        if not source.is_relative_to(root) or not source.is_file():
            raise SystemExit("An imported material source is missing; migration is incomplete")
        content = source.read_bytes()
        if hashlib.sha256(content).hexdigest() != sha:
            raise SystemExit("Source checksum mismatch; no object was overwritten")
        try:
            existing = storage.download(key, 100 * 1024 * 1024)
        except storage.StorageUnavailable:
            storage.put(key, content)
            copied += 1
        else:
            if hashlib.sha256(existing).hexdigest() != sha:
                raise SystemExit("Cloud checksum mismatch; no object was overwritten")
            verified += 1
    print(
        f"Source migration finished: {copied} copied, {verified} already matched. Local originals preserved."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(Path.home() / "LernyData/secrets/cloud-app.json"))
    parser.add_argument("--source-root", default=str(Path.home() / "LernyData/data/files"))
    args = parser.parse_args()
    migrate(args.config, args.source_root)
