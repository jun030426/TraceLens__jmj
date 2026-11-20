"""Compile a narration JSON into one offline Lerny Video Agent request."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
from lerny.heygen_lecture_profile import compile_script_request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lesson", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    body = compile_script_request(
        json.loads(args.lesson.read_text(encoding="utf-8-sig"))
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "request.json").write_text(
        json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / "video-agent-prompt.txt").write_text(
        body["prompt"], encoding="utf-8"
    )
    print(json.dumps({"submitted": False, "prompt_characters": len(body["prompt"])}))


if __name__ == "__main__":
    main()
