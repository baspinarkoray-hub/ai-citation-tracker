import json
import pathlib

import yaml

from tracker.engines import parse_aio, parse_openai, parse_perplexity
from tracker.report import aggregate, to_markdown
from tracker.scoring import Brands, score

ROOT = pathlib.Path(__file__).resolve().parent.parent
BRANDS = Brands(yaml.safe_load((ROOT / "config/brands.yaml").read_text()))

OPENAI_SAMPLE = {"output": [
    {"type": "web_search_call", "status": "completed"},
    {"type": "message", "content": [{"type": "output_text",
        "text": "Spot BTC ETFs took in $1.2B this week, per The Block and Farside.",
        "annotations": [
            {"type": "url_citation", "url": "https://farside.co.uk/btc/"},
            {"type": "url_citation", "url": "https://www.theblock.co/data/etfs/bitcoin-etf?utm=x"},
            {"type": "url_citation", "url": "https://farside.co.uk/btc/"}]}]}]}

PPLX_SAMPLE = {"output": [
    {"type": "search_results", "results": [
        {"id": 1, "url": "https://www.coindesk.com/x"},
        {"id": 2, "url": "https://defillama.com/stablecoins"},
        {"id": 3, "url": "https://example.com/unused"}]},
    {"type": "message", "content": [{"type": "output_text",
        "text": "Stablecoin cap is ~$300B per DefiLlama[2][1]. Growth continues[2].", "annotations": []}]}]}

AIO_SAMPLE = {"ai_overview": {"text_blocks": [{"type": "paragraph", "snippet": "Strategy holds the most BTC."}],
              "references": [{"index": 1, "link": "https://bitcointreasuries.net/"},
                             {"index": 0, "link": "https://www.theblock.co/post/123/strategy-buys"}]}}


def test_openai():
    r = parse_openai(OPENAI_SAMPLE)
    assert r["citations"] == ["https://farside.co.uk/btc/", "https://www.theblock.co/data/etfs/bitcoin-etf?utm=x"]
    s = score(r, BRANDS, "https://www.theblock.co/data/etfs/bitcoin-etf")
    assert s["own_cited"] and s["own_best_position"] == 2 and s["own_target_hit"]
    assert "farside" in s["cited_brands"] and "theblock" in s["mentioned_brands"]
    assert s["own_url_type"] == ["data"]


def test_perplexity():
    r = parse_perplexity(PPLX_SAMPLE)
    assert r["citations"] == ["https://defillama.com/stablecoins", "https://www.coindesk.com/x"]
    s = score(r, BRANDS, "https://www.theblock.co/data/stablecoins/usd-pegged")
    assert not s["own_cited"] and s["cited_brands"] == ["coindesk", "defillama"]


def test_aio_order_and_absent():
    r = parse_aio(AIO_SAMPLE)
    assert r["present"] and r["citations"][0].startswith("https://www.theblock.co")
    s = score(r, BRANDS)
    assert s["own_best_position"] == 1 and s["own_url_type"] == ["article"]
    assert parse_aio({})["present"] is False


def test_report_end_to_end():
    cfg = yaml.safe_load((ROOT / "config/brands.yaml").read_text())
    runs = []
    for eng, parsed, tgt in [("chatgpt", parse_openai(OPENAI_SAMPLE), "https://www.theblock.co/data/etfs/bitcoin-etf"),
                             ("perplexity", parse_perplexity(PPLX_SAMPLE), None),
                             ("google_aio", parse_aio(AIO_SAMPLE), None)]:
        runs.append({"date": "2026-10-19", "engine": eng, "prompt_id": "p1", "repeat": 1, "topic": "etfs",
                     "intent": "live", "ok": True, "aio_present": parsed.get("present"),
                     **score(parsed, BRANDS, tgt)})
    s = aggregate(runs, cfg)
    assert s["engines"]["chatgpt"]["own_citation_rate"] == 100.0
    assert s["engines"]["perplexity"]["own_citation_rate"] == 0.0
    md = to_markdown(s, {"p1": {"text": "test"}})
    assert "Opportunities" in md and "perplexity" in md
    json.dumps(s)
