"""Run the EA-100 protocol against a model.

Protocol (from the spec):
  * same minimal system prompt for every task
  * one fresh conversation per task (no context leakage)
  * no web/retrieval/code tools for the Core
  * low temperature, same sampling settings across tasks
  * record latency / tokens / throughput; report quality and speed separately
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .client import ChatClient
from .tasks import load_tasks, parse_task_filter, task_map
from .util import resolve_api_key

DEFAULT_SYSTEM = "You are a helpful general-purpose assistant."


def _run_one(client: ChatClient, task: dict, model_cfg: dict, cfg: dict,
             print_lock: threading.Lock, done_count: list[int], total: int) -> dict:
    kind = task["kind"]
    system = cfg.get("system_prompt", DEFAULT_SYSTEM)
    sampling = cfg.get("sampling", {})

    if kind == "image_gen":
        if not model_cfg.get("image_gen"):
            return {"id": task["id"], "status": "skipped",
                    "reason": "image generation not enabled for this model (stack/tool task, excluded from Core score)"}
        # A real stack runner would invoke the image tool here and save the artifact.
        return {"id": task["id"], "status": "skipped",
                "reason": "image generation is a tool/stack capability; run outside this harness and record manually"}

    user_content: str | list = task["prompt"]
    if kind == "vision":
        if not model_cfg.get("vision"):
            return {"id": task["id"], "status": "skipped",
                    "reason": "vision not enabled for this model (excluded from Core score)"}
        img_rel = task.get("image")
        assets = Path(cfg.get("assets_dir", "assets"))
        img_path = assets / img_rel if img_rel else None
        if not (img_path and img_path.exists()):
            return {"id": task["id"], "status": "error", "error": f"missing image asset {img_path}"}
        # Point the model at the attached image instead of a file path.
        prompt = re.sub(r"`?assets/visual_task_\d+\.png`?", "the attached image", task["prompt"])
        user_content = [
            {"type": "text", "text": prompt},
            client.image_message(img_path),
        ]

    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user_content}]
    try:
        out = client.chat(
            messages,
            model=model_cfg["model"],
            temperature=sampling.get("temperature", 0.0),
            max_tokens=sampling.get("max_tokens", 4096),
        )
    except RuntimeError as e:
        return {"id": task["id"], "status": "error", "error": str(e)[:500]}

    toks = out["completion_tokens"] or 0
    tok_s = round(toks / out["latency_s"], 1) if out["latency_s"] > 0 and toks else None
    with print_lock:
        done_count[0] += 1
        n = done_count[0]
        print(f"[{n}/{total}] task {task['id']:>3} {task['title'][:44]:<44} "
              f"{toks:>5} tok {out['latency_s']:>6.1f}s {str(tok_s or '-'):>7} tok/s", flush=True)
    return {
        "id": task["id"],
        "status": "done",
        "title": task["title"],
        "category": task["category"],
        "kind": kind,
        "prompt": task["prompt"],
        "response": out["text"],
        "prompt_tokens": out["prompt_tokens"],
        "completion_tokens": toks,
        "latency_s": out["latency_s"],
        "tokens_per_s": tok_s,
        "prompt_tokens_per_s": out.get("prompt_tokens_per_s"),   # llama.cpp timings
        "generation_tokens_per_s": out.get("generation_tokens_per_s"),  # llama.cpp timings
        "finish_reason": out["finish_reason"],
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "_ran_now": True,
    }


def run_benchmark(cfg: dict, model_name: str, task_filter: str | None = None,
                  parallel: int = 1, force: bool = False, run_dir: str | None = None) -> Path:
    payload = load_tasks(cfg.get("tasks_json"))
    model_cfg = cfg["models"][model_name]
    ids = parse_task_filter(task_filter, payload)
    tasks = [t for t in payload["tasks"] if t["id"] in ids]
    tasks.sort(key=lambda t: t["id"])

    base_url = model_cfg.get("base_url") or cfg.get("base_url")
    if not base_url:
        raise SystemExit(f"error: no base_url for model '{model_name}'")
    api_key = resolve_api_key(model_cfg.get("api_key_env") or model_cfg.get("api_key"))
    client = ChatClient(base_url, api_key,
                        timeout=model_cfg.get("timeout", cfg.get("timeout", 300)),
                        max_retries=model_cfg.get("max_retries", cfg.get("max_retries", 3)),
                        verify_ssl=model_cfg.get("verify_ssl", True))

    out_dir = Path(run_dir or cfg.get("runs_dir", "runs")) / model_name
    out_dir.mkdir(parents=True, exist_ok=True)
    resp_path = out_dir / "responses.json"
    existing: dict[int, dict] = {}
    if resp_path.exists():
        for entry in json.loads(resp_path.read_text(encoding="utf-8")):
            if force and entry["id"] in ids:
                continue  # re-run tasks in the filter
            existing[entry["id"]] = entry  # keep everything else (also resume case)

    todo = [t for t in tasks if t["id"] not in existing]
    skip = [t for t in tasks if t["id"] in existing]
    if skip:
        print(f"resume: {len(skip)} tasks already recorded, {len(todo)} to run "
              f"(use --force to re-run everything)")

    print(f"EA-100 run: model='{model_name}' tasks={len(todo)} parallel={parallel} "
          f"endpoint={base_url} system_prompt='{cfg.get('system_prompt', DEFAULT_SYSTEM)}'")

    print_lock = threading.Lock()
    done_count = [0]
    results: list[dict] = list(existing.values())

    if todo:
        with ThreadPoolExecutor(max_workers=max(1, parallel)) as ex:
            futs = {ex.submit(_run_one, client, t, model_cfg, cfg, print_lock, done_count, len(todo)): t for t in todo}
            for fut in as_completed(futs):
                results.append(fut.result())
        results.sort(key=lambda r: r["id"])
        resp_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    # -- metadata ------------------------------------------------------------
    done = [r for r in results if r["status"] == "done"]
    skipped = [r for r in results if r["status"] == "skipped"]
    errors = [r for r in results if r["status"] == "error"]
    ran_now = [r for r in results if r.get("_ran_now")]
    for r in results:
        r.pop("_ran_now", None)
    ran_done = [r for r in ran_now if r["status"] == "done"]
    lat = [r["latency_s"] for r in ran_done]
    toks = [r["completion_tokens"] for r in ran_done]
    pp_s = [r["prompt_tokens_per_s"] for r in ran_done if r.get("prompt_tokens_per_s")]
    gen_s = [r["generation_tokens_per_s"] for r in ran_done if r.get("generation_tokens_per_s")]
    if ran_now:
        first_ts = min(r["timestamp"] for r in ran_now if r.get("timestamp"))
    else:
        first_ts = next((r.get("timestamp") for r in results if r.get("timestamp")), None)
    wall = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(first_ts) if first_ts else dt.timedelta(0)

    meta = {
        "benchmark": payload.get("name", "EA-100"),
        "model_name": model_name,
        "model": model_cfg.get("model", model_name),
        "base_url": base_url,
        "endpoint_note": "API" if "http" in base_url else base_url,
        "meta": model_cfg.get("meta", {}),          # quant/backend/hardware/context/notes
        "system_prompt": cfg.get("system_prompt", DEFAULT_SYSTEM),
        "sampling": cfg.get("sampling", {}),
        "protocol": {
            "fresh_conversation_per_task": True,
            "tools_enabled": False,
            "temperature": cfg.get("sampling", {}).get("temperature", 0.0),
        },
        "timing": {
            "started": results[0]["timestamp"] if results else None,
            "finished": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "wall_seconds": round(wall.total_seconds(), 1),
            "avg_latency_s": round(sum(lat) / len(lat), 2) if lat else None,
            "avg_completion_tokens": round(sum(toks) / len(toks), 1) if toks else None,
            "avg_tokens_per_s": round(sum(toks) / sum(lat), 1) if lat and sum(lat) > 0 else None,
            "avg_prompt_tokens_per_s": round(sum(pp_s) / len(pp_s), 1) if pp_s else None,
            "avg_generation_tokens_per_s": round(sum(gen_s) / len(gen_s), 1) if gen_s else None,
        },
        "counts": {
            "attempted": len(results),
            "done": len(done),
            "skipped": len(skipped),
            "errors": len(errors),
        },
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nthis run: {len(ran_done)} done, {len(ran_now) - len(ran_done)} skipped/errored in "
          f"{meta['timing']['wall_seconds']}s · file total: {len(done)} done, {len(skipped)} skipped, "
          f"{len(errors)} errors -> {out_dir}")
    for r in errors:
        print(f"  ERROR task {r['id']}: {r['error'][:160]}")
    for r in skipped:
        print(f"  SKIP  task {r['id']}: {r['reason']}")
    return out_dir
