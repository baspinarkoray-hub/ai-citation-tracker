"""Engine adapters. Each returns a normalized dict:
{"answer": str, "citations": [url, ...]}  (citations in display order)
"""
from __future__ import annotations

import os
import time

import requests

TIMEOUT = 120


class EngineError(RuntimeError):
    pass


def _post(url: str, headers: dict, payload: dict, retries: int = 3) -> dict:
    for attempt in range(retries):
        r = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(5 * (attempt + 1))
            continue
        if not r.ok:
            raise EngineError(f"{r.status_code}: {r.text[:300]}")
        return r.json()
    raise EngineError(f"gave up after {retries} retries ({r.status_code})")


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
    answer = ""
    choices = data.get("choices") or []
    if choices:
        answer = choices[0].get("message", {}).get("content", "")
    cites = list(data.get("citations") or [])
    if not cites:
        cites = [s.get("url") for s in data.get("search_results") or []]
    return {"answer": answer, "citations": _dedupe(cites)}


def run_perplexity(prompt: str) -> dict:
    key = os.environ.get("PERPLEXITY_API_KEY")
    if not key:
        raise EngineError("PERPLEXITY_API_KEY missing")
    payload = {
        "model": os.environ.get("PERPLEXITY_MODEL", "sonar"),
        "messages": [{"role": "user", "content": prompt}],
    }
    data = _post(
        "https://api.perplexity.ai/chat/completions",
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
