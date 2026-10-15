"""Engine adapters. Each returns a normalized dict:
{"answer": str, "citations": [url, ...]}  (citations in display order)
"""
from __future__ import annotations

import os
import re
import time

import requests

TIMEOUT = 120


class EngineError(RuntimeError):
    pass


def _post(url: str, headers: dict, payload: dict, retries: int = 4) -> dict:
    for attempt in range(retries):
        r = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
        # out of credits is a 429 too, but retrying won't help
        if r.status_code == 429 and "insufficient_quota" in r.text:
            raise EngineError(f"429 insufficient_quota (no API credits): {r.text[:300]}")
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(10 * (attempt + 1))
            continue
        if not r.ok:
            raise EngineError(f"{r.status_code}: {r.text[:300]}")
        return r.json()
    raise EngineError(f"gave up after {retries} retries ({r.status_code}): {r.text[:300]}")


def _get(url: str, params: dict, retries: int = 3) -> dict:
    for attempt in range(retries):
        r = requests.get(url, params=params, timeout=TIMEOUT)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(5 * (attempt + 1))
            continue
        if not r.ok:
            raise EngineError(f"{r.status_code}: {r.text[:300]}")
        return r.json()
    raise EngineError(f"gave up after {retries} retries ({r.status_code})")


def _dedupe(urls):
    seen, out = set(), []
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


# ---------------------------------------------------------------- OpenAI ---
def parse_openai(data: dict) -> dict:
    answer_parts, cites = [], []
    for item in data.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    answer_parts.append(c.get("text", ""))
                    for a in c.get("annotations", []):
                        if a.get("type") == "url_citation":
                            cites.append(a.get("url"))
    return {"answer": "\n".join(answer_parts), "citations": _dedupe(cites)}


def run_openai(prompt: str) -> dict:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise EngineError("OPENAI_API_KEY missing")
    payload = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-5-mini"),
        "tools": [{"type": "web_search"}],
        "tool_choice": "required",
        "input": prompt,
    }
    data = _post(
        "https://api.openai.com/v1/responses",
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        payload,
    )
    return parse_openai(data)


# ------------------------------------------------------------ Perplexity ---
def parse_perplexity(data: dict) -> dict:
    """Perplexity Agent API (/v1/agent). Sources live in a `search_results`
    output item; the answer cites them inline as [1][3]. Citations = sources
    referenced inline, in order of first reference; if none are referenced,
    all retrieved sources."""
    answer_parts, results = [], {}
    for item in data.get("output", []):
        if item.get("type") == "search_results":
            for res in item.get("results", []):
                results[res.get("id")] = res.get("url")
        elif item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    answer_parts.append(c.get("text", ""))
    answer = "\n".join(answer_parts)
    refs = [int(n) for n in re.findall(r"\[(\d+)\]", answer)]
    cites = [results[n] for n in refs if n in results]
    if not cites:
        cites = list(results.values())
    return {"answer": answer, "citations": _dedupe(cites)}


def run_perplexity(prompt: str) -> dict:
    key = os.environ.get("PERPLEXITY_API_KEY")
    if not key:
        raise EngineError("PERPLEXITY_API_KEY missing")
    payload = {
        "preset": os.environ.get("PERPLEXITY_PRESET", "fast"),
        "input": prompt,
    }
    data = _post(
        "https://api.perplexity.ai/v1/agent",
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        payload,
    )
    return parse_perplexity(data)


# --------------------------------------------- Google AI Overviews (SerpApi) ---
def _aio_text(aio: dict) -> str:
    out = []
    for b in aio.get("text_blocks", []) or []:
        if b.get("snippet"):
            out.append(b["snippet"])
        for li in b.get("list", []) or []:
            if li.get("snippet"):
                out.append(li["snippet"])
    return "\n".join(out)


def parse_aio(data: dict) -> dict:
    """Returns {"answer", "citations", "present": bool}."""
    aio = data.get("ai_overview") or {}
    if not aio or aio.get("error"):
        return {"answer": "", "citations": [], "present": False}
    refs = sorted(aio.get("references", []) or [], key=lambda r: r.get("index", 0))
    return {
        "answer": _aio_text(aio),
        "citations": _dedupe([r.get("link") for r in refs]),
        "present": True,
    }


def run_aio(prompt: str) -> dict:
    key = os.environ.get("SERPAPI_API_KEY")
    if not key:
        raise EngineError("SERPAPI_API_KEY missing")
    base = "https://serpapi.com/search.json"
    data = _get(base, {"engine": "google", "q": prompt, "gl": "us", "hl": "en",
                       "no_cache": "true", "api_key": key})
    aio = data.get("ai_overview") or {}
    # AI Overview is sometimes deferred and needs a second call with page_token
    if aio.get("page_token") and not aio.get("text_blocks"):
        data = _get(base, {"engine": "google_ai_overview",
                           "page_token": aio["page_token"], "api_key": key})
    return parse_aio(data)


ENGINES = {
    "chatgpt": run_openai,
    "perplexity": run_perplexity,
    "google_aio": run_aio,
}
