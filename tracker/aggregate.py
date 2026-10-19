"""Turn the raw per-day cache into the two published CSVs.

data/topic_daily.csv   date, source, topic, items, points, authors
data/source_daily.csv  date, source, items, points, authors

items   = number of stories / papers / models that matched (or the day's total)
points  = HN points, HF paper upvotes, or HF model likes, as of collection time
authors = distinct HN submitters or distinct HF model owners (blank for papers)

Rebuilding from raw means a change to topics.csv never needs a re-download.
"""
import csv
import datetime as dt
from collections import defaultdict
from multiprocessing import Pool

from .common import DATA, RAW, read_raw
from .topics import load_topics, match, model_text

SOURCES = ["hn", "hf_papers", "hf_models"]
_topics = None


def _init():
    global _topics
    _topics = load_topics()


def _item(source, row):
    """Return (text, points, author, match kwargs) for one raw row."""
    if source == "hn":
        return row["title"], row["points"], row["author"], {"require_ai_context": True}
    if source == "hf_papers":
        return f"{row['title']}\n{row['summary']}", row["upvotes"], None, {}
    owner = row["id"].split("/")[0] if "/" in row["id"] else row["id"]
    return model_text(row["id"], row["tags"]), row["likes"], owner, {"machine_text": True}


def _aggregate_day(args):
    source, day = args
    total = {"items": 0, "points": 0, "authors": set()}
    per = defaultdict(lambda: {"items": 0, "points": 0, "authors": set()})
    for row in read_raw(source, day):
        text, points, author, kw = _item(source, row)
        total["items"] += 1
        total["points"] += points
        if author:
            total["authors"].add(author)
        for t in match(text, _topics, **kw):
            per[t]["items"] += 1
            per[t]["points"] += points
            if author:
                per[t]["authors"].add(author)
    has_authors = source != "hf_papers"

    def fmt(d):
        return [d["items"], d["points"], len(d["authors"]) if has_authors else ""]

    totals_row = [day.isoformat(), source, *fmt(total)]
    topic_rows = [[day.isoformat(), source, t, *fmt(d)] for t, d in sorted(per.items())]
    return totals_row, topic_rows


def build(processes=8):
    jobs = []
    for source in SOURCES:
        for p in sorted((RAW / source).glob("*.jsonl.gz")):
            jobs.append((source, dt.date.fromisoformat(p.name[:10])))
    with Pool(processes, initializer=_init) as pool:
        results = pool.map(_aggregate_day, jobs, chunksize=4)
    results.sort(key=lambda r: (r[0][0], r[0][1]))
    with open(DATA / "source_daily.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "source", "items", "points", "authors"])
        w.writerows(r[0] for r in results)
    with open(DATA / "topic_daily.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "source", "topic", "items", "points", "authors"])
        for r in results:
            w.writerows(r[1])
    return len(jobs)
