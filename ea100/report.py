"""Generate the EA-100 markdown report + CSV exports for one or more runs."""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from .tasks import core_ids, load_tasks, task_map


def load_run(run_dir: str, tasks_json: str | None = None) -> tuple[dict, dict, dict, dict]:
    run = Path(run_dir)
    payload = load_tasks(tasks_json)
    tmap = task_map(payload)
    entries = json.loads((run / "responses.json").read_text(encoding="utf-8")) if (run / "responses.json").exists() else []
    grades = json.loads((run / "grades.json").read_text(encoding="utf-8")) if (run / "grades.json").exists() else []
    meta = json.loads((run / "meta.json").read_text(encoding="utf-8")) if (run / "meta.json").exists() else {}
    return payload, tmap, entries, grades, meta


def _grade_map(grades: list[dict]) -> dict[int, dict]:
    return {g["id"]: g for g in grades}


def summarize(payload: dict, tmap: dict[int, dict], entries: list[dict], grades: list[dict]) -> dict:
    gmap = _grade_map(grades)
    core = [t["id"] for t in payload["tasks"] if t["id"] in core_ids(payload)]
    vt = payload["vision_tool_ids"]

    def bucket(ids: list[int]) -> dict:
        graded = [i for i in ids if i in gmap]
        totals = [gmap[i]["total"] for i in graded]
        skipped = [e["id"] for e in entries if e["id"] in ids and e["status"] != "done"]
        return {
            "task_ids": ids, "graded": graded, "n_graded": len(graded),
            "n_skipped": len(skipped), "skipped": skipped,
            "sum": sum(totals), "mean": (sum(totals) / len(totals)) if totals else None,
            "gates": [i for i in graded if gmap[i].get("gate_violation")],
        }

    by_cat: dict[str, list[int]] = defaultdict(list)
    for t in payload["tasks"]:
        by_cat[t["category"]].append(t["id"])

    return {
        "core": bucket(core),
        "vision_tool": bucket(vt),
        "all": bucket([t["id"] for t in payload["tasks"]]),
        "by_category": {c: bucket(ids) for c, ids in by_cat.items()},
        "gmap": gmap,
    }


def render_report(run_dir: str, tasks_json: str | None = None, compare: list[str] | None = None,
                  out: str | None = None) -> Path:
    payload, tmap, entries, grades, meta = load_run(run_dir, tasks_json)
    s = summarize(payload, tmap, entries, grades)
    run = Path(run_dir)
    out_path = Path(out) if out else run / "report.md"

    L = []
    def A(line: str = ""):
        L.append(line)
    A(f"# EA-100 Benchmark Report — {meta.get('model_name', run.name)}")
    A()
    A(f"Generated: {meta.get('timing', {}).get('finished', 'n/a')} · "
      f"Benchmark: {payload.get('name')} v{payload.get('version')} · Source: {payload.get('source')}")
    A()

    # ---- metadata ----
    A("## Run metadata")
    A()
    A("| Field | Value |")
    A("|---|---|")
    m = meta.get("meta", {})
    for k in ("quantization", "backend", "hardware", "context", "notes"):
        if m.get(k):
            A(f"| {k} | {m[k]} |")
    A(f"| model | {meta.get('model')} |")
    A(f"| endpoint | {meta.get('base_url')} |")
    A(f"| system prompt | `{meta.get('system_prompt')}` |")
    A(f"| sampling | {json.dumps(meta.get('sampling', {}))} |")
    A(f"| fresh conversation per task | {meta.get('protocol', {}).get('fresh_conversation_per_task')} |")
    A(f"| tools enabled | {meta.get('protocol', {}).get('tools_enabled')} |")
    t = meta.get("timing", {})
    # Prefer timing derived from the recorded entries over the (per-invocation) meta.
    done_entries = [e for e in entries if e["status"] == "done"]
    if done_entries:
        stamps = [e.get("timestamp") for e in entries if e.get("timestamp")]
        lat_l = [e["latency_s"] for e in done_entries]
        tok_l = [e["completion_tokens"] for e in done_entries]
        pp_l = [e["prompt_tokens_per_s"] for e in done_entries if e.get("prompt_tokens_per_s")]
        gen_l = [e["generation_tokens_per_s"] for e in done_entries if e.get("generation_tokens_per_s")]
        if stamps:
            from datetime import datetime

            t0 = min(datetime.fromisoformat(s) for s in stamps)
            t1 = max(datetime.fromisoformat(s) for s in stamps)
            A(f"| wall time | {(t1 - t0).total_seconds():.0f}s |")
        A(f"| avg latency/task | {sum(lat_l) / len(lat_l):.1f}s |")
        if sum(lat_l) > 0:
            A(f"| avg throughput | {sum(tok_l) / sum(lat_l):.1f} tok/s |")
        if pp_l:
            A(f"| **avg prompt processing** | **{sum(pp_l) / len(pp_l):.1f} tok/s** |")
        if gen_l:
            A(f"| **avg generation** | **{sum(gen_l) / len(gen_l):.1f} tok/s** |")
    elif t.get("wall_seconds") is not None:
        A(f"| wall time | {t['wall_seconds']}s |")
        A(f"| avg latency/task | {t.get('avg_latency_s')}s |")
        if t.get("avg_prompt_tokens_per_s"):
            A(f"| **avg prompt processing** | **{t['avg_prompt_tokens_per_s']} tok/s** |")
        if t.get("avg_generation_tokens_per_s"):
            A(f"| **avg generation** | **{t['avg_generation_tokens_per_s']} tok/s** |")
        elif t.get("avg_tokens_per_s"):
            A(f"| avg generation | {t['avg_tokens_per_s']} tok/s |")
    A()

    # ---- headline scores ----
    A("## Scores")
    A()
    if not s["gmap"]:
        A("_No grades yet — run `python3 bench.py grade --config <cfg> --run <dir>` first._")
        A()
        A("---")
        A(f"*Judge: human · Report generated by the EA-100 harness (stdlib-only, no external deps).*")
        out_path.write_text("\n".join(L), encoding="utf-8")
        print(f"report written to {out_path} (no grades)")
        return out_path
    A("| Metric | Value | Basis |")
    A("|---|---|---|")
    c = s["core"]
    core_pct = (c["sum"] / (10 * c["n_graded"]) * 100) if c["n_graded"] else None
    core_nominal = (c["sum"] / 960 * 100) if c["n_graded"] else None
    A(f"| **Core score** (96 text tasks) | **{core_pct:.1f}/100** | {c['n_graded']}/96 graded" +
      (f", {c['n_skipped']} skipped, {c['sum']}/{'%.0f' % (10 * c['n_graded'])} pts (nominal w/ missing=0: {core_nominal:.1f})" if c["n_skipped"] else f", {c['sum']}/960 pts") + " |")
    v = s["vision_tool"]
    vt_mean = v["mean"]
    A(f"| Vision/tool extension (tasks 63,64,88,89) | {vt_mean if vt_mean is None else f'{vt_mean:.1f}/10'} | {v['n_graded']}/4 graded" +
      (" (not measured — image capability not tested)" if v["n_graded"] == 0 else "") + " |")
    a = s["all"]
    full_pct = (a["sum"] / (10 * a["n_graded"]) * 100) if a["n_graded"] else None
    full_nominal = (a["sum"] / 1000 * 100) if a["n_graded"] else None
    A(f"| **Full Assistant score** | **{full_pct:.1f}/100** | {a['n_graded']}/100 graded" +
      (f", {a['n_skipped']} skipped, nominal w/ missing=0: {full_nominal:.1f}" if a["n_skipped"] else f", {a['sum']}/1000 pts") + " |")
    if c["gates"]:
        A(f"| ⚠ hard-gate violations | tasks {', '.join(map(str, c['gates']))} | see task table |")
    A()
    A("*Core = tasks 1-62, 65-87, 90-100 (excludes image-gen 63-64 and vision 88-89); "
      "scores normalized to the graded subset when tasks are skipped.*")
    A()

    # ---- category breakdown ----
    A("## By category")
    A()
    A("| Category | Tasks | Mean /10 | Σ |")
    A("|---|---:|---:|---:|")
    for cat, b in sorted(s["by_category"].items(), key=lambda kv: -(kv[1]["mean"] or -1)):
        mean = f"{b['mean']:.2f}" if b["mean"] is not None else "—"
        A(f"| {cat} | {b['n_graded']}/{len(b['task_ids'])} | {mean} | {b['sum']} |")
    A()

    # ---- per-task table ----
    A("## Per-task scores")
    A()
    A("| # | Task | Cat | Dims c+i+r+c+s | Tot | Notes |")
    A("|---|---|---|---:|---:|---|")
    gmap = s["gmap"]
    for e in sorted(entries, key=lambda x: x["id"]):
        tid = e["id"]
        t = tmap[tid]
        if e["status"] != "done":
            A(f"| {tid} | {t['title']} | {t['category']} | — | — | _{e.get('reason') or e.get('error', '')}_ |")
            continue
        g = gmap.get(tid)
        if not g:
            A(f"| {tid} | {t['title']} | {t['category']} | — | — | _not graded_ |")
            continue
        sc = g["scores"]
        dims = f"{sc['correctness']}+{sc['instruction_following']}+{sc['reasoning']}+{sc['communication']}+{sc['safety']}"
        gate = " ⚠" if g.get("gate_violation") else ""
        A(f"| {tid} | {t['title']} | {t['category']} | {dims} | {g['total']}{gate} | {g.get('notes', '')[:90]} |")
    A()

    # ---- speed summary (reported separately from quality) ----
    A("## Speed / cost (reported separately from quality)")
    A()
    A("| Metric | Value |")
    A("|---|---|")
    done = [e for e in entries if e["status"] == "done"]
    lat = [e["latency_s"] for e in done]
    toks = [e["completion_tokens"] for e in done]
    pp = [e["prompt_tokens_per_s"] for e in done if e.get("prompt_tokens_per_s")]
    gen = [e["generation_tokens_per_s"] for e in done if e.get("generation_tokens_per_s")]
    if lat:
        A(f"| avg latency | {sum(lat)/len(lat):.1f}s |")
        A(f"| avg completion tokens | {sum(toks)/len(toks):.0f} |")
        A(f"| avg throughput | {sum(toks)/sum(lat):.1f} tok/s |")
        A(f"| total completion tokens | {sum(toks)} |")
    if pp:
        A(f"| **avg prompt processing** | **{sum(pp)/len(pp):.1f} tok/s** |")
    if gen:
        A(f"| **avg generation** | **{sum(gen)/len(gen):.1f} tok/s** |")
    A(f"| done / skipped / errors | {meta.get('counts', {}).get('done')} / {meta.get('counts', {}).get('skipped')} / {meta.get('counts', {}).get('errors')} |")
    A()
    A("---")
    A(f"*Judge: {', '.join(sorted({g.get('judge_model') for g in gmap.values()})) or 'human'} · "
      f"Report generated by the EA-100 harness (stdlib-only, no external deps).*")

    out_path.write_text("\n".join(L), encoding="utf-8")
    print(f"report written to {out_path}")

    # CSV export
    csv_path = run / "scores.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["task_id", "title", "category", "total", "correctness", "instruction_following",
                    "reasoning", "communication", "safety", "gate_violation", "notes"])
        for e in sorted(entries, key=lambda x: x["id"]):
            g = gmap.get(e["id"])
            t = tmap[e["id"]]
            if g:
                w.writerow([e["id"], t["title"], t["category"], g["total"], *[g["scores"][k] for k in
                            ("correctness", "instruction_following", "reasoning", "communication", "safety")],
                            g.get("gate_violation") or "", g.get("notes", "")])
            else:
                w.writerow([e["id"], t["title"], t["category"], "", "", "", "", "", "", "", ""])
    print(f"scores csv written to {csv_path}")

    # ---- compare mode ----
    if compare:
        render_compare([run_dir] + compare, tasks_json)
    return out_path


def render_compare(run_dirs: list[str], tasks_json: str | None = None) -> Path:
    out = Path("runs") / "compare.md"
    rows = []
    for rd in run_dirs:
        payload, tmap, entries, grades, meta = load_run(rd, tasks_json)
        s = summarize(payload, tmap, entries, grades)
        c, v, a = s["core"], s["vision_tool"], s["all"]
        rows.append({
            "name": meta.get("model_name", Path(rd).name),
            "core": (c["sum"] / (10 * c["n_graded"]) * 100) if c["n_graded"] else None,
            "core_n": c["n_graded"],
            "vt": v["mean"],
            "full": (a["sum"] / (10 * a["n_graded"]) * 100) if a["n_graded"] else None,
            "tok_s": meta.get("timing", {}).get("avg_tokens_per_s"),
            "backend": meta.get("meta", {}).get("backend", ""),
            "gates": len(c["gates"]) + len(s["vision_tool"]["gates"]),
        })
    L = ["# EA-100 comparison", "", "| Model | Core /100 | Full /100 | Vision/tool /10 | tok/s | gates | backend |",
         "|---|---:|---:|---:|---:|---:|---|"]
    for r in rows:
        L.append(f"| {r['name']} | {r['core']:.1f} ({r['core_n']}/96) | {r['full']:.1f} | "
                 f"{r['vt'] if r['vt'] is None else round(r['vt'], 1)} | {r['tok_s'] or '-'} | {r['gates']} | {r['backend']} |")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"comparison written to {out}")
    return out
