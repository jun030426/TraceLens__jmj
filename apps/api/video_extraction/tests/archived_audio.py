"""Test-only replay of archived evidence under the current calculations.

Production correctly rejects running an old plan after a code update. These
regressions deliberately replay frozen responses; substitute only the archived
finalizer fingerprint, retaining every source/snapshot/clip integrity check.
Never import this helper from production or use it to execute a historical plan.
"""
from unittest.mock import patch
from video_extraction.audio import audio_finalize
from video_extraction.shared.common import read


def replay_fingerprint():
    live=audio_finalize.hashes()
    archived=read(audio_finalize.OUT/'plan.json')['code_hashes']
    # Frozen responses do not invoke the changed ASR worker. Its detected-language
    # metadata change must not invalidate this test-only historic content replay.
    replay={k:archived[k] for k in ('audio_finalize.py','audio_coverage_local.py')}
    return patch.object(audio_finalize,'hashes',return_value={**live,**replay})
