"""Bind an existing local MP4 to a section's local preview. No API calls or generation."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))

from lerny.lecture_playback import LocalLecture, PlaybackError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--section-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--script-file", type=Path)
    parser.add_argument("--replace", action="store_true")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--test-video", type=Path)
    source.add_argument("--run-id")
    args = parser.parse_args()
    try:
        script = args.script_file.read_text(encoding="utf-8-sig") if args.script_file else ""
        state = LocalLecture(args.runtime_root, args.section_id).bind(
            title=args.title,
            script=script,
            test_video=args.test_video,
            run_id=args.run_id,
            replace=args.replace,
        )
    except (PlaybackError, OSError, ValueError) as exc:
        parser.error(
            str(exc) if isinstance(exc, PlaybackError) else "Invalid local file or metadata"
        )
    print(json.dumps(state, ensure_ascii=False))


if __name__ == "__main__":
    main()
