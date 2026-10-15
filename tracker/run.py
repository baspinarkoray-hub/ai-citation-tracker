"""Run the prompt set against each engine and append results to data/raw/<date>.jsonl

Usage:
  python -m tracker.run                       # all engines, all prompts, 3 repeats
  python -m tracker.run --engines perplexity --limit 5 --repeats 1   # quick test
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import yaml

from tracker.engines import ENGINES, EngineError
from tracker.scoring import Brands, score

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load(path: str) -> dict:
    return yaml.safe_load((ROOT / path).read_text())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engines", default=",".join(ENGINES), help="comma list")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0, help="only first N prompts")
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args(argv)

    prompts = load("config/prompts.yaml")["prompts"]
    if args.limit:
        prompts = prompts[: args.limit]
    brands = Brands(load("config/brands.yaml"))
    engines = [e.strip() for e in args.engines.split(",") if e.strip()]

    today = dt.date.today().isoformat()
    out_dir = ROOT / "data" / "raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{today}.jsonl"

    jobs = [(e, p, r) for e in engines for p in prompts for r in range(1, args.repeats + 1)]
    print(f"{len(jobs)} calls → {out_path.relative_to(ROOT)}")

    def work(engine, p, rep):
        rec = {"date": today, "engine": engine, "prompt_id": p["id"], "repeat": rep,
               "topic": p["topic"], "intent": p["intent"], "target": p.get("target"),
               "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
        try:
            res = ENGINES[engine](p["text"])
            rec.update({"ok": True, "answer": res["answer"], "aio_present": res.get("present"),
                        **score(res, brands, p.get("target"))})
        except (EngineError, Exception) as e:  # keep the batch alive
            rec.update({"ok": False, "error": str(e)[:500]})
        return rec

    errors = 0
    with open(out_path, "a") as f, ThreadPoolExecutor(args.workers) as pool:
        futs = [pool.submit(work, *j) for j in jobs]
        for i, fut in enumerate(as_completed(futs), 1):
            rec = fut.result()
            errors += not rec["ok"]
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if i % 25 == 0 or i == len(jobs):
                print(f"  {i}/{len(jobs)} done, {errors} errors")

    if errors == len(jobs):
        print("All calls failed — check API keys.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
