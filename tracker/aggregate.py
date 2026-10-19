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
    seen_urls = set()
    for row in read_raw(source, day):
        if source == "hn" and row["url"]:
            # The same link is often submitted several times a day; count it once.
            url = row["url"].split("#")[0].rstrip("/").lower().replace("://www.", "://")
            if url in seen_urls:
                continue
            seen_urls.add(url)
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

    # Upsert: rows for the (date, source) pairs rebuilt here replace the old ones,
    # everything else in the existing CSVs is kept. With the full raw cache this is
    # a full rebuild; in the daily job, where only recent days are cached, it is an update.
    rebuilt = {(r[0][0], r[0][1]) for r in results}
    totals = _keep(DATA / "source_daily.csv", rebuilt) + [r[0] for r in results]
    topics = _keep(DATA / "topic_daily.csv", rebuilt) + [row for r in results for row in r[1]]
    _write(DATA / "source_daily.csv", ["date", "source", "items", "points", "authors"], totals, 2)
    _write(DATA / "topic_daily.csv", ["date", "source", "topic", "items", "points", "authors"], topics, 3)
    return len(jobs)


def _keep(path, rebuilt):
    if not path.exists():
        return []
    with open(path, newline="") as f:
        rows = list(csv.reader(f))[1:]
    return [row for row in rows if (row[0], row[1]) not in rebuilt]


def _write(path, header, rows, key_len):
    rows.sort(key=lambda r: tuple(str(x) for x in r[:key_len]))
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
