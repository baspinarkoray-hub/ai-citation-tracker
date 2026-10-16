"""Treatment-vs-control view of the data-page experiment (config/experiment.yaml).

A run belongs to a page when its prompt's `target` is that page. For each
group we report, on the answers to that group's prompts:
  cited      % of answers citing any theblock.co URL
  data_page  % citing a The Block data product (/data, /treasuries, /etfs, /price)
  target     % citing the experiment page itself (or one of its chart sub-pages)
"""
from __future__ import annotations

import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_PREFIXES = ("/data", "/treasuries", "/etfs", "/price", "/indices")


def load_config():
    path = ROOT / "config" / "experiment.yaml"
    return yaml.safe_load(path.read_text()) if path.exists() else None


def _path(url: str) -> str:
    return "/" + url.split("theblock.co", 1)[-1].lstrip("/").split("?")[0].split("#")[0].rstrip("/")


def _pct(n, d):
    return round(100 * n / d, 1) if d else None


def group_of(cfg) -> dict[str, tuple[str, int]]:
    """page path -> (group, pair index)"""
    out = {}
    for i, p in enumerate(cfg["pairs"]):
        out[p["treatment"].rstrip("/")] = ("treatment", i)
        out[p["control"].rstrip("/")] = ("control", i)
    return out


def _stats(runs, page=None):
    def hit_target(r):
        pg = page or _path(r.get("target") or "")
        return any(_path(u) == pg or _path(u).startswith(pg + "/") for u in r.get("own_urls", []))
    return {
        "answers": len(runs),
        "cited": _pct(sum(r["own_cited"] for r in runs), len(runs)),
        "data_page": _pct(sum(any(_path(u).startswith(DATA_PREFIXES) for u in r.get("own_urls", [])) for r in runs), len(runs)),
        "target": _pct(sum(hit_target(r) for r in runs), len(runs)),
    }


def summarize(runs: list[dict], cfg=None) -> dict | None:
    """runs: successful runs of one measurement date (AIO runs without an overview already removed)."""
    cfg = cfg or load_config()
    if not cfg:
        return None
    groups = group_of(cfg)
    tagged = [(groups.get(_path(r.get("target") or "")), r) for r in runs]
    out = {"name": cfg["name"], "week0": cfg.get("week0"), "groups": {}, "pairs": []}
    for g in ("treatment", "control"):
        out["groups"][g] = _stats([r for t, r in tagged if t and t[0] == g])
    for i, p in enumerate(cfg["pairs"]):
        row = {"topic": p["topic"]}
        for g in ("treatment", "control"):
            page = p[g].rstrip("/")
            row[g] = {"page": page, **_stats([r for t, r in tagged if t == (g, i)], page)}
        out["pairs"].append(row)
    return out


def markdown(e: dict | None) -> list[str]:
    if not e:
        return []
    f = lambda v: "–" if v is None else v
    L = ["", f"## Experiment — {e['name']}", "",
         f"Treatment live since: {e['week0'] or 'not yet (pre-launch baseline)'}", "",
         "| Group | Answers | Cited % | Data page % | Target page % |", "|---|---|---|---|---|"]
    for g, s in e["groups"].items():
        L.append(f"| {g} | {s['answers']} | {f(s['cited'])} | {f(s['data_page'])} | {f(s['target'])} |")
    L += ["", "| Topic | Treatment page | T target % | Control page | C target % |", "|---|---|---|---|---|"]
    for p in e["pairs"]:
        L.append(f"| {p['topic']} | {p['treatment']['page']} | {f(p['treatment']['target'])} | "
                 f"{p['control']['page']} | {f(p['control']['target'])} |")
    return L
