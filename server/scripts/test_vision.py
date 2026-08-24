"""Ad-hoc CLI to exercise agent.vision.parse_medbox against real photos.

Not part of the app or CI — a standalone way to sanity-check OCR quality against
data/test_photos before the full server (assets upload, /api/parse/medbox route) exists.

Usage:
    DASHSCOPE_API_KEY=... .venv/bin/python scripts/test_vision.py \
        ../data/test_photos/5982.JPG [more.jpg ...]

Multiple paths are treated as multiple angles of the SAME pill box (spec: "usually 2
photos: front and the dosage side") and passed to one parse_medbox() call together. To
test photos as separate boxes, run the script once per photo instead.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.llm import LLMUnavailable  # noqa: E402
from agent.vision import parse_medbox  # noqa: E402


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1

    image_urls = []
    for raw_path in argv:
        path = Path(raw_path).resolve()
        if not path.exists():
            print(f"✗ file not found: {path}")
            return 1
        image_urls.append(f"file://{path}")

    print(f"Parsing {len(image_urls)} photo(s) as one pill box:")
    for u in image_urls:
        print(f"  {u}")
    print()

    try:
        result = parse_medbox(image_urls)
    except LLMUnavailable as exc:
        print(f"✗ LLMUnavailable: {exc}")
        return 1

    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))

    if result.missing:
        print(f"\n⚠ missing fields: {result.missing}")
    low_conf = {k: v for k, v in result.confidence.items() if v < 0.7}
    if low_conf:
        print(f"⚠ low-confidence fields (<0.7): {low_conf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
