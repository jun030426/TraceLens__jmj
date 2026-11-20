"""Private source snapshots of eligible PPTs from the video's own course/week."""
import json
import shutil
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from lerny.db import engine
from lerny.models import Material, MaterialVersion


def eligible(material, version, owner):
    return bool(material and version and owner and not material.deleted and
                material.course_id == owner.course_id and material.week == owner.week and
                material.visibility == 'public' and material.internal_use == 'none' and
                material.kind == 'lecture' and material.active_version_id == version.id and
                version.material_id == material.id and version.status == 'ready' and
                Path(version.filename).suffix.lower() == '.pptx')


def verify(references, owner_version_id):
    from lerny.media_materials import file_digest, MediaStopped
    with Session(engine()) as db:
        owner_version = db.get(MaterialVersion, owner_version_id)
        owner = db.get(Material, owner_version.material_id) if owner_version else None
        if not owner or owner.deleted:
            raise MediaStopped('SOURCE_REVOKED')
        for ref in references:
            version = db.get(MaterialVersion, ref['version_id'])
            material = db.get(Material, ref['material_id'])
            if not eligible(material, version, owner) or version.sha256 != ref['sha256']:
                raise MediaStopped('MEDIA_REFERENCE_CHANGED')
            if file_digest(ref['path']) != ref['sha256']:
                raise MediaStopped('SOURCE_CHANGED')


def snapshot(owner_version_id, folder):
    from lerny.media_materials import file_digest, MediaStopped
    from lerny.storage import source_file
    from lerny.gemini_provider import save_json
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    manifest = folder/'materials.json'
    if manifest.exists():
        references = json.loads(manifest.read_text(encoding='utf-8'))
        verify(references, owner_version_id)
        return references
    references = []
    with Session(engine()) as db:
        owner_version = db.get(MaterialVersion, owner_version_id)
        owner = db.get(Material, owner_version.material_id) if owner_version else None
        if not owner or owner.deleted:
            raise MediaStopped('SOURCE_REVOKED')
        # A batch upload can queue video extraction before PPT embedding finishes.
        # Yield the worker so the newest eligible PPT can become ready, rather
        # than freezing an empty/older reference manifest for the whole video.
        candidates = db.scalars(select(Material).where(
            Material.course_id == owner.course_id, Material.week == owner.week,
            Material.deleted.is_(False), Material.visibility == 'public',
            Material.internal_use == 'none', Material.kind == 'lecture')).all()
        for candidate in candidates:
            latest = db.scalar(select(MaterialVersion).where(
                MaterialVersion.material_id == candidate.id).order_by(
                MaterialVersion.version_no.desc()).limit(1))
            if (latest and Path(latest.filename).suffix.lower() == '.pptx'
                    and latest.status in {'queued', 'processing', 'extracting', 'extracted', 'embedding'}):
                raise MediaStopped('MEDIA_REFERENCE_WAIT', retry_at=time.time()+30)
        rows = db.execute(select(Material, MaterialVersion).join(MaterialVersion,
            Material.active_version_id == MaterialVersion.id).where(
            Material.course_id == owner.course_id, Material.week == owner.week,
            Material.deleted.is_(False), Material.visibility == 'public',
            Material.internal_use == 'none', Material.kind == 'lecture',
            MaterialVersion.status == 'ready').order_by(Material.id)).all()
        for material, version in rows:
            if not eligible(material, version, owner):
                continue
            target = folder/(version.sha256+'.pptx')
            if not target.exists():
                with source_file(version) as original:
                    shutil.copyfile(original, target)
            if file_digest(target) != version.sha256:
                raise MediaStopped('SOURCE_CHANGED')
            references.append({'material_id': material.id, 'version_id': version.id,
                               'sha256': version.sha256, 'path': str(target.resolve())})
    verify(references, owner_version_id)
    save_json(manifest, references)
    return references
