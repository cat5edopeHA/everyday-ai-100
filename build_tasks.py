#!/usr/bin/env python3
"""Parse the EA-100 benchmark markdown spec into structured JSON.

Usage:
    python3 build_tasks.py --md EA-100_Everyday_AI_Benchmark.md --out data/ea100_tasks.json

Re-runnable: regenerate the dataset any time the spec markdown changes.
"""
import argparse
import json
import re
import sys
from pathlib import Path

TASK_RE = re.compile(r"^### Task (\d+):\s*(.+)$")
CAT_RE = re.compile(r"^##\s+(.+)$")


def parse_spec(md_text: str) -> list[dict]:
    tasks: list[dict] = []
    category = "Uncategorized"
    current = None
    state = "idle"  # idle | prompt | notes
    prompt_lines: list[str] = []
    notes: list[str] = []

    for raw in md_text.splitlines():
        line = raw.rstrip()

        cat_m = CAT_RE.match(line)
        if cat_m and not line.startswith("### "):
            category = cat_m.group(1).strip()
            state = "idle"
            continue

        task_m = TASK_RE.match(line)
        if task_m:
            if current is not None:
                current["prompt"] = "\n".join(prompt_lines).strip()
                current["evaluator_notes"] = notes
                tasks.append(current)
            current = {
                "id": int(task_m.group(1)),
                "title": task_m.group(2).strip(),
                "category": category,
                "kind": "text",
            }
            prompt_lines = []
            notes = []
            state = "prompt"
            continue

        if current is None:
            continue

        if state == "prompt":
            if line == "**Prompt**":
                pass  # marker line, not part of the prompt text
            elif line.startswith(">"):
                # strip exactly the "> " quote prefix, preserving code indentation
                prompt_lines.append(line[2:] if line.startswith("> ") else line[1:])
            elif line.startswith("![") and "assets/visual_task_" in line:
                # image reference attached to a vision task
                m = re.search(r"\((assets/visual_task_\d+\.png)\)", line)
                if m:
                    current["image"] = m.group(1)
            elif "**Evaluator notes**" in line:
                state = "notes"
            elif line.strip() == "":
                pass
            else:
                # Non-quote text inside the prompt region (e.g. stray prose).
                prompt_lines.append(line)
        elif state == "notes":
            if line.startswith("- "):
                notes.append(line[2:].strip())
            elif line.strip() == "":
                pass
            else:
                state = "idle"

    if current is not None:
        current["prompt"] = "\n".join(prompt_lines).strip()
        current["evaluator_notes"] = notes
        tasks.append(current)

    # Classify special tasks
    for t in tasks:
        if t["category"] == "Image generation":
            t["kind"] = "image_gen"
        elif t.get("image"):
            t["kind"] = "vision"

    # Validate contiguous numbering
    ids = [t["id"] for t in tasks]
    assert ids == list(range(1, len(ids) + 1)), f"task numbering not contiguous: {ids}"
    return tasks


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--assets-dir", default="assets", help="dir where vision PNGs live")
    args = ap.parse_args()

    md_text = Path(args.md).read_text(encoding="utf-8")
    tasks = parse_spec(md_text)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": "EA-100",
        "version": "1.0",
        "source": Path(args.md).name,
        "task_count": len(tasks),
        "core_ids": [t["id"] for t in tasks if t["kind"] == "text"],
        "vision_tool_ids": [t["id"] for t in tasks if t["kind"] != "text"],
        "assets_dir": args.assets_dir,
        "tasks": tasks,
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    from collections import Counter

    counts = Counter(t["category"] for t in tasks)
    print(f"Parsed {len(tasks)} tasks from {Path(args.md).name} -> {out}")
    print(f"  text: {len(payload['core_ids'])}, vision/tool: {len(payload['vision_tool_ids'])}")
    for cat, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>3}  {cat}")


if __name__ == "__main__":
    sys.exit(main())
