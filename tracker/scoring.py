"""Turns a raw engine result into brand-level citation/mention facts."""
from __future__ import annotations

import re
from urllib.parse import urlparse


class Brands:
    def __init__(self, cfg: dict):
        self.own = cfg["own"]
        self.brands = cfg["brands"]
        self._mention_re = {
            k: [re.compile(p, re.I) for p in v.get("mentions", [])]
            for k, v in self.brands.items()
        }

    def brand_for_url(self, url: str) -> str | None:
        host = (urlparse(url).hostname or "").lower()
        for key, b in self.brands.items():
            for d in b["domains"]:
                if host == d or host.endswith("." + d):
                    return key
        return None

    def mentioned(self, text: str) -> set[str]:
        return {k for k, pats in self._mention_re.items() if any(p.search(text or "") for p in pats)}


def score(result: dict, brands: Brands, target: str | None = None) -> dict:
    """Per-run facts used by the report."""
    cites = result.get("citations", [])
    cited = []  # (brand, position, url)
    for pos, url in enumerate(cites, start=1):
        b = brands.brand_for_url(url)
        cited.append({"brand": b, "position": pos, "url": url})

    own = brands.own
    own_cites = [c for c in cited if c["brand"] == own]
    norm = lambda u: (u or "").split("?")[0].split("#")[0].rstrip("/")
    return {
        "n_citations": len(cites),
        "cited_brands": sorted({c["brand"] for c in cited if c["brand"]}),
        "mentioned_brands": sorted(brands.mentioned(result.get("answer", ""))),
        "own_cited": bool(own_cites),
        "own_best_position": min((c["position"] for c in own_cites), default=None),
        "own_urls": [c["url"] for c in own_cites],
        "own_target_hit": any(norm(c["url"]).startswith(norm(target)) for c in own_cites) if target else False,
        "own_url_type": sorted({_url_type(c["url"]) for c in own_cites}),
        "citations": cited,
    }


def _url_type(url: str) -> str:
    path = urlparse(url).path
    for prefix, label in [("/data", "data"), ("/price", "price"), ("/etfs", "etf-tracker"),
                          ("/treasuries", "data"), ("/post", "article"), ("/news", "article"),
                          ("/learn", "learn"), ("/research", "research")]:
        if path.startswith(prefix):
            return label
    return "other"
