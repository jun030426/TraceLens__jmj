"""Reuse source-bound ASR observations, never earlier acceptance decisions."""
import json
import re
import shutil
import time
from pathlib import Path


def reuse_asr_cache(output, plan, search_root=None):
    output = Path(output)
    source = plan['source_plan']
    identity = sorted(s['source_sha256'] for s in source['sources'])
    model = source.get('local_whisper')
    if not model:
        return 0
    copied = 0
    for previous in sorted(Path(search_root or output.parent).glob('analysis-*/plan.json')):
        if previous.parent == output:
            continue
        old = json.loads(previous.read_text())['source_plan']
        if (sorted(s['source_sha256'] for s in old['sources']) != identity
                or old.get('local_whisper') != model):
            continue
        for cache in sorted((previous.parent/'whisper-cache').glob('*.json')):
            if not re.fullmatch(r'[a-f0-9]{64}\.json', cache.name):
                continue
            entry = json.loads(cache.read_text())
            if (entry.get('signature') != cache.stem or entry.get('provider') != 'local_whisper'
                    or not isinstance(entry.get('text'), str) or not isinstance(entry.get('segments'), list)):
                continue
            target = output/'whisper-cache'/cache.name
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cache, target)
            copied += 1
    return copied


def check_time_slice(started, duration=30*60):
    # Called BEFORE transport. In-flight paid calls always finish and are cached.
    # A queued continuation retains its generation, source and validation results.
    if time.monotonic()-started >= duration:
        from lerny.media_materials import MediaStopped
        raise MediaStopped('MEDIA_CONTINUATION_WAIT', retry_at=time.time()+5)
