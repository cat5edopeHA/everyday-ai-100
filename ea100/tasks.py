"""EA-100 task dataset loading and scoring constants."""
from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_TASKS_JSON = DATA_DIR / "ea100_tasks.json"


def load_tasks(path: str | Path | None = None) -> dict:
    """Load the parsed EA-100 dataset. Returns the full payload dict."""
    path = Path(path or DEFAULT_TASKS_JSON)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found — run `python3 build_tasks.py --md <spec.md> --out data/ea100_tasks.json` first"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def task_map(payload: dict) -> dict[int, dict]:
    return {t["id"]: t for t in payload["tasks"]}


def core_ids(payload: dict) -> list[int]:
    """96 text tasks: 1-62, 65-87, 90-100 (per the spec's Core score)."""
    return payload["core_ids"]


def vision_tool_ids(payload: dict) -> list[int]:
    """Tasks 63, 64 (image generation) and 88, 89 (image analysis)."""
    return payload["vision_tool_ids"]


def parse_task_filter(spec: str | None, payload: dict) -> set[int]:
    """Parse a --tasks filter: 'all', 'core', 'vision', or '1-10,58-62,88-89'."""
    all_ids = {t["id"] for t in payload["tasks"]}
    if not spec or spec.strip().lower() in ("all", ""):
        return all_ids
    spec = spec.strip().lower()
    if spec == "core":
        return set(core_ids(payload))
    if spec == "vision":
        return set(vision_tool_ids(payload))
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out & all_ids
