"""Same-course/week and public-only reference selection in isolated SQLite."""
import hashlib
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from lerny import media_references, storage
from lerny.media_materials import MediaStopped
from lerny.models import Material, MaterialVersion


def test_reference_snapshot_excludes_private_answers_other_courses_and_stale_versions(tmp_path, monkeypatch):
    isolated = create_engine('sqlite:///'+str(tmp_path/'references.sqlite'))
    Material.__table__.create(isolated)
    MaterialVersion.__table__.create(isolated)
    monkeypatch.setattr(media_references, 'engine', lambda: isolated)
    original = tmp_path/'original.pptx'
    original.write_bytes(b'synthetic source; not parsed by this authorization test')
    sha = hashlib.sha256(original.read_bytes()).hexdigest()
    opened = []
    @contextmanager
    def source(version):
        opened.append(version.id)
        yield original
    monkeypatch.setattr(storage, 'source_file', source)
    with Session(isolated) as db:
        def material(mid, **kw):
            values = dict(id=mid, course_id='own', title=mid, week=2, visibility='public',
                          kind='lecture', internal_use='none', active_version_id=mid+'-version', deleted=False)
            values.update(kw)
            m = Material(**values)
            v = MaterialVersion(id=mid+'-version', material_id=mid, version_no=1,
                filename='same-name.pptx', object_key=mid+'.pptx', sha256=sha, status='ready')
            db.add_all([m,v])
            return m,v
        _, owner = material('video')
        owner.filename = 'video.mp4'
        material('allowed')
        material('other-course', course_id='other')
        material('other-week', week=3)
        material('private', visibility='private')
        material('answer', kind='answer', internal_use='answer')
        material('deleted', deleted=True)
        material('stale', active_version_id='superseded-version')
        _, pending = material('pending')
        pending.status = 'failed'
        db.commit()
    refs = media_references.snapshot('video-version', tmp_path/'snapshot')
    assert [r['material_id'] for r in refs] == ['allowed']
    assert opened == ['allowed-version']
    assert media_references.snapshot('video-version', tmp_path/'snapshot') == refs
    assert opened == ['allowed-version']
    with Session(isolated) as db:
        db.get(Material, 'allowed').visibility = 'private'
        db.commit()
    with pytest.raises(MediaStopped, match='MEDIA_REFERENCE_CHANGED'):
        media_references.verify(refs, 'video-version')


def test_batch_video_waits_for_latest_ppt_without_freezing_empty_manifest(tmp_path, monkeypatch):
    isolated = create_engine('sqlite:///'+str(tmp_path/'batch.sqlite'))
    Material.__table__.create(isolated)
    MaterialVersion.__table__.create(isolated)
    monkeypatch.setattr(media_references, 'engine', lambda: isolated)
    original = tmp_path/'source.pptx'; original.write_bytes(b'synthetic batch source')
    sha = hashlib.sha256(original.read_bytes()).hexdigest()
    @contextmanager
    def source(version):
        yield original
    monkeypatch.setattr(storage, 'source_file', source)
    with Session(isolated) as db:
        for mid,filename,status in [('video','video.mp4','queued'),('ppt','slides.pptx','extracted')]:
            db.add(Material(id=mid,course_id='own',title=mid,week=1,kind='lecture',visibility='public'))
            db.add(MaterialVersion(id=mid+'-v1',material_id=mid,version_no=1,filename=filename,
                                   object_key=filename,sha256=sha,status=status))
        db.commit()
    folder=tmp_path/'snapshot'
    with pytest.raises(MediaStopped, match='MEDIA_REFERENCE_WAIT') as stopped:
        media_references.snapshot('video-v1',folder)
    assert stopped.value.retry_at and not (folder/'materials.json').exists()
    with Session(isolated) as db:
        db.get(MaterialVersion,'ppt-v1').status='ready'
        db.get(Material,'ppt').active_version_id='ppt-v1'
        db.commit()
    refs=media_references.snapshot('video-v1',folder)
    assert [r['version_id'] for r in refs]==['ppt-v1']
