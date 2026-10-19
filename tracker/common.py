"""Shared helpers: HTTP session with polite retries, and the raw per-day cache."""
import datetime as dt
import gzip
import json
import time
from pathlib import Path

import requests

DATA = Path(__file__).resolve().parent.parent / "data"
RAW = DATA / "raw"

session = requests.Session()
session.headers["User-Agent"] = "ai-attention-tracker/0.1 (public research; contact via github.com/ZiqiWang-Zoe)"


def get(url, params=None, tries=8):
    """GET with backoff on 429 and 5xx. Honors Hugging Face's ratelimit header."""
    for attempt in range(tries):
        try:
            r = session.get(url, params=params, timeout=60)
        except requests.RequestException:
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 200:
            _respect_hf_ratelimit(r)
            return r
        if r.status_code == 429 or r.status_code >= 500:
            wait = _hf_reset_seconds(r) or 2 ** attempt
            time.sleep(min(wait + 1, 320))
            continue
        r.raise_for_status()
    raise RuntimeError(f"giving up on {url} {params}")


def _hf_reset_seconds(r):
    # Header looks like: "api";r=497;t=203  (r = requests left, t = seconds until reset)
    h = r.headers.get("ratelimit", "")
    parts = dict(p.split("=") for p in h.split(";")[1:] if "=" in p)
    return int(parts["t"]) if "t" in parts else None


def _respect_hf_ratelimit(r):
    h = r.headers.get("ratelimit", "")
    parts = dict(p.split("=") for p in h.split(";")[1:] if "=" in p)
    if "r" in parts and int(parts["r"]) < 5:
        time.sleep(int(parts.get("t", 60)) + 1)


def days(start, end):
    d = start
    while d <= end:
        yield d
        d += dt.timedelta(days=1)


def raw_path(source, day):
    return RAW / source / f"{day.isoformat()}.jsonl.gz"


def write_raw(source, day, rows):
    p = raw_path(source, day)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with gzip.open(tmp, "wt") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.rename(p)


def read_raw(source, day):
    with gzip.open(raw_path(source, day), "rt") as f:
        for line in f:
            yield json.loads(line)
