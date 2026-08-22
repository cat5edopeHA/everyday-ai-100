"""Shared helpers: config loading, key resolution, tolerant JSON parsing."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


def load_config(path: str | Path) -> dict:
    """Load a config file. YAML when PyYAML is available, else JSON.
    JSON is a valid subset of YAML for our purposes, so a .json file works everywhere."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # optional dependency

        return yaml.safe_load(text) or {}
    except ImportError:
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            print(f"error: {path} is not valid JSON and PyYAML is not installed: {e}", file=sys.stderr)
            print("  install pyyaml (`pip install pyyaml`) or write the config as JSON.", file=sys.stderr)
            sys.exit(2)


def resolve_api_key(spec: str | None, config_dict: dict | None = None) -> str | None:
    """Resolve an api_key or api_key_env spec to a key string (never printed).
    spec may be: None (no auth), a literal key, or an env var NAME.
    config_dict: optional fallback dict (e.g. {'env': {...}}), unused for now."""
    if not spec:
        return None
    spec = spec.strip()
    # Load .env-style files if the var is not exported. HOME can be a sandboxed
    # dir (e.g. WebUI boxes), so also try the real system home via pwd.
    if spec in os.environ:
        return os.environ[spec]
    candidates = []
    try:
        import pwd

        candidates.append(Path(pwd.getpwuid(os.getuid()).pw_dir) / ".hermes" / ".env")
    except (ImportError, KeyError):
        pass
    candidates += [Path.home() / ".hermes" / ".env", Path.home() / ".env", Path.cwd() / ".env"]
    for candidate in candidates:
        if candidate.exists():
            m = re.search(rf"^{re.escape(spec)}=(.+)$", candidate.read_text(encoding="utf-8"), re.M)
            if m:
                return m.group(1).strip().strip('"').strip("'")
    # A bare value that is not an env var and not obviously a key path: treat as literal key.
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", spec):
        print(f"warning: api_key_env '{spec}' not found in environment or ~/.hermes/.env", file=sys.stderr)
        return None
    return spec


def extract_json_object(text: str) -> dict:
    """Tolerantly pull a JSON object out of a model response."""
    text = (text or "").strip()
    # Strip markdown fences if present
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    # Last resort: regex each known field
    out = {}
    for key in ("correctness", "instruction_following", "reasoning", "communication", "safety", "total"):
        m = re.search(rf'"{key}"\s*:\s*(\d+)', text)
        if m:
            out[key] = int(m.group(1))
    m = re.search(r'"notes"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    if m:
        out["notes"] = m.group(1)
    return out


def clamp(v, lo, hi):
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except (TypeError, ValueError):
        return lo
