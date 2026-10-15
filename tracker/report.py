"""Aggregate data/raw/*.jsonl into:
  data/summary.json      — machine-readable, feeds the dashboard later
  reports/<date>.md      — human-readable weekly report

Usage: python -m tracker.report [--date YYYY-MM-DD]   (default: latest raw file)
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import statistics

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent


def pct(n, d):
    return round(100 * n / d, 1) if d else 0.0


def load_runs(date: str):
    path = ROOT / "data" / "raw" / f"{date}.jsonl"
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def aggregate(runs: list[dict], brands_cfg: dict) -> dict:
    own = brands_cfg["own"]
    ok = [r for r in runs if r.get("ok")]
    engines = sorted({r["engine"] for r in ok})
    labels = {k: v["label"] for k, v in brands_cfg["brands"].items()}

    out = {"date": runs[0]["date"] if runs else None, "n_calls": len(runs),
           "n_errors": len(runs) - len(ok), "engines": {}, "topics": {}, "prompts": {}}

    for eng in engines:
        er = [r for r in ok if r["engine"] == eng]
        # AIO: only count runs where an overview actually appeared
        if eng == "google_aio":
            shown = [r for r in er if r.get("aio_present")]
            aio_rate = pct(len(shown), len(er))
            er = shown
        else:
            aio_rate = None
        total_cites = sum(r["n_citations"] for r in er)
        brand_cites = collections.Counter()
        brand_runs = collections.Counter()
        brand_mentions = collections.Counter()
        for r in er:
            for c in r["citations"]:
                if c["brand"]:
                    brand_cites[c["brand"]] += 1
            for b in r["cited_brands"]:
                brand_runs[b] += 1
            for b in r["mentioned_brands"]:
                brand_mentions[b] += 1
        positions = [r["own_best_position"] for r in er if r["own_best_position"]]
        out["engines"][eng] = {
            "runs": len(er),
            "aio_present_rate": aio_rate,
            "own_citation_rate": pct(sum(r["own_cited"] for r in er), len(er)),
            "own_target_hit_rate": pct(sum(r["own_target_hit"] for r in er), len(er)),
            "own_citation_share": pct(brand_cites[own], total_cites),
            "own_mention_rate": pct(brand_mentions[own], len(er)),
            "own_avg_position": round(statistics.mean(positions), 1) if positions else None,
            "brands": sorted(
                [{"brand": b, "label": labels.get(b, b),
                  "citation_rate": pct(brand_runs[b], len(er)),
                  "citation_share": pct(brand_cites[b], total_cites),
                  "mention_rate": pct(brand_mentions[b], len(er))}
                 for b in labels],
                key=lambda x: -x["citation_rate"]),
            "top_domains": collections.Counter(
                (c["url"].split("/")[2] if "://" in c["url"] else c["url"])
                for r in er for c in r["citations"]).most_common(15),
        }

    for topic in sorted({r["topic"] for r in ok}):
        tr = [r for r in ok if r["topic"] == topic and (r["engine"] != "google_aio" or r.get("aio_present"))]
        out["topics"][topic] = {"runs": len(tr), "own_citation_rate": pct(sum(r["own_cited"] for r in tr), len(tr))}

    by_prompt = collections.defaultdict(list)
    for r in ok:
        by_prompt[(r["prompt_id"], r["engine"])].append(r)
    for (pid, eng), rs in by_prompt.items():
        comp = collections.Counter(b for r in rs for b in r["cited_brands"] if b != own)
        out["prompts"].setdefault(pid, {})[eng] = {
            "own_cited": sum(r["own_cited"] for r in rs), "of": len(rs),
            "competitors": [labels.get(b, b) for b, _ in comp.most_common(3)],
        }
    return out


def to_markdown(s: dict, prompts: dict) -> str:
    L = [f"# AI Citation Report — {s['date']}", "",
         f"{s['n_calls']} calls, {s['n_errors']} errors.", "",
         "## The Block by engine", "",
         "| Engine | Cited in % of answers | Target page hit % | Citation share % | Mentioned % | Avg position |",
         "|---|---|---|---|---|---|"]
    for eng, e in s["engines"].items():
        name = eng + (f" (AIO shown {e['aio_present_rate']}%)" if e["aio_present_rate"] is not None else "")
        L.append(f"| {name} | {e['own_citation_rate']} | {e['own_target_hit_rate']} | "
                 f"{e['own_citation_share']} | {e['own_mention_rate']} | {e['own_avg_position'] or '–'} |")

    for eng, e in s["engines"].items():
        L += ["", f"## Leaderboard — {eng}", "", "| Brand | Cited in % | Share of citations % | Mentioned % |", "|---|---|---|---|"]
        for b in e["brands"]:
            if b["citation_rate"] or b["mention_rate"]:
                L.append(f"| {b['label']} | {b['citation_rate']} | {b['citation_share']} | {b['mention_rate']} |")
        L += ["", "Top cited domains: " + ", ".join(f"{d} ({n})" for d, n in e["top_domains"][:10])]

    L += ["", "## By topic (all engines)", "", "| Topic | Cited in % |", "|---|---|"]
    for t, v in s["topics"].items():
        L.append(f"| {t} | {v['own_citation_rate']} |")

    L += ["", "## Opportunities — prompts where competitors are cited and The Block never is", ""]
    for pid, engs in sorted(s["prompts"].items()):
        lost = [(eng, v) for eng, v in engs.items() if v["own_cited"] == 0 and v["competitors"]]
        if lost:
            txt = prompts.get(pid, {}).get("text", pid)
            who = "; ".join(f"{eng}: {', '.join(v['competitors'])}" for eng, v in lost)
            L.append(f"- **{pid}** — {txt}  \n  ↳ {who}")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    a = ap.parse_args(argv)
    raw = sorted((ROOT / "data" / "raw").glob("*.jsonl"))
    date = a.date or raw[-1].stem
    brands_cfg = yaml.safe_load((ROOT / "config/brands.yaml").read_text())
    prompts = {p["id"]: p for p in yaml.safe_load((ROOT / "config/prompts.yaml").read_text())["prompts"]}

    s = aggregate(load_runs(date), brands_cfg)
    hist_path = ROOT / "data" / "summary.json"
    hist = json.loads(hist_path.read_text()) if hist_path.exists() else {"weeks": []}
    hist["weeks"] = [w for w in hist["weeks"] if w["date"] != date] + [s]
    hist["weeks"].sort(key=lambda w: w["date"])
    hist_path.write_text(json.dumps(hist, indent=1, ensure_ascii=False))

    (ROOT / "reports").mkdir(exist_ok=True)
    md = to_markdown(s, prompts)
    (ROOT / "reports" / f"{date}.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
