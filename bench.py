#!/usr/bin/env python3
"""EA-100 benchmark harness CLI.

Subcommands:
  parse   rebuild data/ea100_tasks.json from the spec markdown
  run     execute the 100 tasks against a model (fresh conversations, temp 0)
  grade   score responses with an LLM judge (0-10 rubric) or manual CSV
  report  generate the markdown report (+ --compare across runs)
  all     run + grade + report in one go

Examples:
  python3 bench.py parse --md EA-100_Everyday_AI_Benchmark.md
  python3 bench.py run --config config.json --model deepseek-flash --parallel 4
  python3 bench.py run --config config.json --model local-qwen --tasks core
  python3 bench.py grade --config config.json --run runs/local-qwen
  python3 bench.py grade --run runs/local-qwen --manual
  python3 bench.py grade --run runs/local-qwen --import runs/local-qwen/scores_manual.csv
  python3 bench.py report --run runs/local-qwen --compare runs/other-model
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ea100.util import load_config  # noqa: E402


def cmd_parse(args) -> int:
    from build_tasks import main as parse_main  # reuses the parser
    sys.argv = ["build_tasks.py", "--md", args.md, "--out", args.out]
    if args.assets_dir:
        sys.argv += ["--assets-dir", args.assets_dir]
    parse_main()
    return 0


def cmd_run(args) -> int:
    from ea100.runner import run_benchmark

    cfg = load_config(args.config)
    run_dir = run_benchmark(cfg, args.model, task_filter=args.tasks,
                            parallel=args.parallel, force=args.force,
                            run_dir=args.run_dir)
    print(f"\nnext: python3 bench.py grade --config {args.config} --run {run_dir}")
    return 0


def cmd_grade(args) -> int:
    from ea100.grader import grade_run

    cfg = {}
    if args.config and Path(args.config).exists():
        cfg = load_config(args.config)
    overrides = {}
    if args.judge_model:
        overrides["model"] = args.judge_model
    if args.judge_base_url:
        overrides["base_url"] = args.judge_base_url
    if args.judge_api_key_env:
        overrides["api_key_env"] = args.judge_api_key_env
    grade_run(cfg, args.run, judge_overrides=overrides, task_filter=args.tasks,
              force=args.force, import_csv=args.import_csv, manual_only=args.manual)
    return 0


def cmd_report(args) -> int:
    from ea100.report import render_report

    render_report(args.run, tasks_json=args.tasks_json, compare=args.compare, out=args.out)
    return 0


def cmd_all(args) -> int:
    from ea100.runner import run_benchmark
    from ea100.grader import grade_run
    from ea100.report import render_report

    cfg = load_config(args.config)
    run_dir = run_benchmark(cfg, args.model, task_filter=args.tasks,
                            parallel=args.parallel, force=args.force,
                            run_dir=args.run_dir)
    grade_run(cfg, str(run_dir), task_filter=args.tasks, force=args.force)
    render_report(str(run_dir), tasks_json=cfg.get("tasks_json"), out=args.out)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="EA-100 reusable LLM benchmark harness")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("parse", help="rebuild the task dataset from the spec markdown")
    p.add_argument("--md", default="EA-100_Everyday_AI_Benchmark.md")
    p.add_argument("--out", default="data/ea100_tasks.json")
    p.add_argument("--assets-dir", default="assets")
    p.set_defaults(fn=cmd_parse)

    p = sub.add_parser("run", help="run tasks against a model")
    p.add_argument("--config", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--tasks", default="all", help="all | core | vision | '1-10,58-62,88-89'")
    p.add_argument("--parallel", type=int, default=1)
    p.add_argument("--force", action="store_true", help="re-run tasks already recorded")
    p.add_argument("--run-dir", default=None, help="override runs/<model> output dir")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("grade", help="score responses (LLM judge or manual CSV)")
    p.add_argument("--config", default="config.json")
    p.add_argument("--run", required=True)
    p.add_argument("--tasks", default="all")
    p.add_argument("--judge-model", default=None)
    p.add_argument("--judge-base-url", default=None)
    p.add_argument("--judge-api-key-env", default=None)
    p.add_argument("--force", action="store_true")
    p.add_argument("--manual", action="store_true", help="write a blank CSV score sheet for human review")
    p.add_argument("--import", dest="import_csv", default=None, help="merge a filled manual CSV")
    p.set_defaults(fn=cmd_grade)

    p = sub.add_parser("report", help="generate the markdown report")
    p.add_argument("--run", required=True)
    p.add_argument("--tasks-json", default=None)
    p.add_argument("--compare", nargs="*", default=None, help="additional run dirs for a comparison table")
    p.add_argument("--out", default=None)
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("all", help="run + grade + report in one go")
    p.add_argument("--config", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--tasks", default="all")
    p.add_argument("--parallel", type=int, default=1)
    p.add_argument("--force", action="store_true")
    p.add_argument("--run-dir", default=None)
    p.add_argument("--out", default=None)
    p.set_defaults(fn=cmd_all)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
