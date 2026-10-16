"""Build site/data.json for the Vercel dashboard from data/raw/*.jsonl.

Every full run date becomes one point on the trend; the latest date gets
the full breakdown (engines, leaderboard, topics, page types, questions).

Usage: python -m tracker.site
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import pathlib

import yaml

from tracker import experiment
from tracker.report import _is_data_url

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENGINES = {"chatgpt": "ChatGPT", "perplexity": "Perplexity", "google_aio": "Google AI Overviews"}
TOPICS = {"etfs": "ETFs", "treasuries": "Treasuries", "stablecoins": "Stablecoins", "markets": "Markets",
          "onchain": "On-chain", "defi": "DeFi", "nfts": "NFTs", "alternative": "Alt. metrics"}
TYPE_LABEL = {"own": "The Block", "media": "Media", "data": "Data platform", "aggregator": "Aggregator"}


def pct(n, d):
    return round(100 * n / d, 1) if d else 0.0


def load_by_date() -> dict[str, list[dict]]:
    by = collections.defaultdict(list)
    for f in sorted((ROOT / "data" / "raw").glob("*.jsonl")):
        for line in f.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("ok") and (r["engine"] != "google_aio" or r.get("aio_present")):
                    by[f.stem[:10]].append(r)
    return dict(sorted(by.items()))


def engine_summary(runs, name):
    tot = sum(r["n_citations"] for r in runs)
    own_links = sum(1 for r in runs for c in r["citations"] if c["brand"] == "theblock")
    pos = [r["own_best_position"] for r in runs if r["own_best_position"]]
    return {
        "engine": name, "answers": len(runs), "citations": tot,
        "cited": pct(sum(r["own_cited"] for r in runs), len(runs)),
        "data_page": pct(sum(any(_is_data_url(u) for u in r.get("own_urls", [])) for r in runs), len(runs)),
        "share": pct(own_links, tot),
        "mentioned": pct(sum("theblock" in r["mentioned_brands"] for r in runs), len(runs)),
        "position": round(sum(pos) / len(pos), 1) if pos else None,
    }


def build():
    brands = yaml.safe_load((ROOT / "config/brands.yaml").read_text())["brands"]
    labels = {k: v["label"] for k, v in brands.items()}
    prompts = {p["id"]: p for p in yaml.safe_load((ROOT / "config/prompts.yaml").read_text())["prompts"]}
    by_date = load_by_date()
    if not by_date:
        raise SystemExit("no full runs in data/raw")

    # --- trend: one point per run date ---
    trend = []
    for date, runs in by_date.items():
        point = {"date": date}
        for key, name in ENGINES.items():
            er = [r for r in runs if r["engine"] == key]
            if er:
                s = engine_summary(er, name)
                point[key] = {"cited": s["cited"], "data_page": s["data_page"]}
        s = engine_summary(runs, "All engines")
        point["all"] = {"cited": s["cited"], "data_page": s["data_page"]}
        ex = experiment.summarize(runs)
        if ex:
            point["experiment"] = ex["groups"]
        trend.append(point)

    # --- latest date detail ---
    date = list(by_date)[-1]
    runs = by_date[date]
    engines = [engine_summary([r for r in runs if r["engine"] == k], n) for k, n in ENGINES.items()
               if any(r["engine"] == k for r in runs)]
    engines.append(engine_summary(runs, "All engines"))

    leaderboard = {}
    for key, name in list(ENGINES.items()) + [(None, "All engines")]:
        er = [r for r in runs if key is None or r["engine"] == key]
        if not er:
            continue
        hits = collections.Counter(b for r in er for b in r["cited_brands"])
        rows = [{"brand": labels[b], "type": TYPE_LABEL[brands[b]["group"]], "cited": pct(hits[b], len(er))}
                for b in labels if hits[b]]
        leaderboard[name] = sorted(rows, key=lambda x: -x["cited"])

    topics = []
    for t, tname in TOPICS.items():
        tr = [r for r in runs if r["topic"] == t]
        if not tr:
            continue
        row = {"topic": tname, "questions": len({r["prompt_id"] for r in tr}), "all": pct(sum(r["own_cited"] for r in tr), len(tr))}
        for key, name in ENGINES.items():
            er = [r for r in tr if r["engine"] == key]
            row[name] = pct(sum(r["own_cited"] for r in er), len(er)) if er else None
        comp = collections.Counter(b for r in tr for b in r["cited_brands"] if b != "theblock")
        if comp:
            b, n = comp.most_common(1)[0]
            row["top_competitor"], row["top_competitor_pct"] = labels[b], pct(n, len(tr))
        topics.append(row)

    page_types = collections.Counter()
    for r in runs:
        for c in r["citations"]:
            if c["brand"] == "theblock":
                path = "/" + c["url"].split("theblock.co", 1)[-1].lstrip("/")
                page_types["Data dashboards (/data)" if path.startswith("/data")
                           else "Data trackers (/treasuries, /etfs, /price)" if _is_data_url(c["url"])
                           else "News & newsletters"] += 1

    domains = collections.Counter((c["url"].split("/")[2] if "://" in c["url"] else c["url"]).removeprefix("www.")
                                  for r in runs for c in r["citations"])

    questions = []
    for pid, p in prompts.items():
        pr = [r for r in runs if r["prompt_id"] == pid]
        if not pr:
            continue
        cited = sum(r["own_cited"] for r in pr)
        comp = collections.Counter(b for r in pr for b in r["cited_brands"] if b != "theblock")
        questions.append({
            "id": pid, "question": p["text"], "topic": TOPICS[p["topic"]],
            "cited": cited, "answers": len(pr), "cited_pct": pct(cited, len(pr)),
            "winners": [f"{labels[b]} ({n})" for b, n in comp.most_common(3)],
            "target": p["target"].replace("https://www.theblock.co", ""),
        })
    questions.sort(key=lambda q: (q["cited_pct"], -len(q["winners"])))

    out = {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
        "date": date, "prompts": len(questions),
        "engines": engines, "trend": trend, "leaderboard": leaderboard, "topics": topics,
        "page_types": [{"type": k, "citations": v} for k, v in page_types.most_common()],
        "domains": [{"domain": d, "citations": n} for d, n in domains.most_common(15)],
        "questions": questions,
        "experiment": experiment.summarize(runs),
    }
    (ROOT / "site").mkdir(exist_ok=True)
    (ROOT / "site" / "data.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"site/data.json: {date}, {len(trend)} run date(s), {len(runs)} answers")


if __name__ == "__main__":
    build()
