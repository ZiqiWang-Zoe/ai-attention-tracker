"""Build the public page.

  python site/build.py                 # snapshot for the latest day + build _site/
  python site/build.py --backfill 45   # also write snapshots for the 45 days before it

Outputs
  snapshots/YYYY-MM-DD.json   one "rising topics" snapshot per day, committed, never rewritten
  _site/index.html            the page (template.html with data inlined)
  _site/data/*.csv            the published CSVs, for download

Counting unit per source:
  hn, hf_papers: items (stories, papers)
  hf_models:     uploader-days (distinct model owners per day, summed), because a
                 single account can upload hundreds of models in a day
"""
import argparse
import csv
import datetime as dt
import json
import os
import shutil
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SNAP = ROOT / "snapshots"
REVIEWS = ROOT / "reviews"
OUT = ROOT / "_site"

SOURCES = {
    "hn": {"label": "Hacker News", "unit": "stories", "metric": "items", "min_recent": 20},
    "hf_papers": {"label": "Hugging Face papers", "unit": "papers", "metric": "items", "min_recent": 20},
    "hf_models": {"label": "Hugging Face models", "unit": "uploaders", "metric": "authors", "min_recent": 50},
}
# Groups left out of rankings: the umbrella topic, the word-choice comparisons, and
# market topics on models (model tags don't talk about jobs or funding).
SKIP_GROUPS = {"overall", "words"}
SKIP_FOR_MODELS = {"market"}
RECENT, BASELINE = 30, 90


def con():
    c = duckdb.connect()
    c.execute(f"""
        CREATE VIEW td AS SELECT date, source, topic, items, coalesce(try_cast(authors AS BIGINT), 0) AS authors
            FROM read_csv('{ROOT}/data/topic_daily.csv', types={{'authors': 'VARCHAR'}});
        CREATE VIEW sd AS SELECT date, source, items, coalesce(try_cast(authors AS BIGINT), 0) AS authors
            FROM read_csv('{ROOT}/data/source_daily.csv', types={{'authors': 'VARCHAR'}});
        CREATE VIEW tp AS SELECT * FROM read_csv('{ROOT}/topics.csv', all_varchar=true);
    """)
    return c


def topics_meta(c):
    return {t: {"label": l, "group": g} for t, l, g in c.execute('SELECT topic, label, "group" FROM tp').fetchall()}


def snapshot(c, as_of, meta):
    r0 = as_of - dt.timedelta(days=RECENT - 1)
    b0 = r0 - dt.timedelta(days=BASELINE)
    snap = {"as_of": as_of.isoformat(), "recent_days": RECENT, "baseline_days": BASELINE, "sources": {}}
    for s, cfg in SOURCES.items():
        m = cfg["metric"]
        rt, bt = c.execute(f"""
            SELECT sum({m}) FILTER (WHERE date >= ?), sum({m}) FILTER (WHERE date < ?)
            FROM sd WHERE source = ? AND date >= ? AND date <= ?""", [r0, r0, s, b0, as_of]).fetchone()
        rows = c.execute(f"""
            SELECT topic, sum({m}) FILTER (WHERE date >= ?), sum({m}) FILTER (WHERE date < ?)
            FROM td WHERE source = ? AND date >= ? AND date <= ? GROUP BY topic""", [r0, r0, s, b0, as_of]).fetchall()
        topics = []
        for topic, r, b in rows:
            g = meta.get(topic, {}).get("group")
            if g in SKIP_GROUPS or (s == "hf_models" and g in SKIP_FOR_MODELS):
                continue
            r, b = r or 0, b or 0
            rs, bs = r / rt, b / bt
            topics.append({"topic": topic, "recent": r, "baseline": b,
                           "recent_share": round(100 * rs, 4), "baseline_share": round(100 * bs, 4),
                           "lift": round(rs / bs, 3) if b else None})
        ranked = [t for t in topics if t["recent"] >= cfg["min_recent"] and t["lift"]]
        ai = c.execute(f"""
            SELECT sum({m}) FILTER (WHERE date >= ?), sum({m}) FILTER (WHERE date < ?)
            FROM td WHERE source = ? AND topic = 'ai_any' AND date >= ? AND date <= ?""", [r0, r0, s, b0, as_of]).fetchone()
        snap["sources"][s] = {
            "recent_total": rt, "baseline_total": bt,
            "ai_share_recent": round(100 * (ai[0] or 0) / rt, 3), "ai_share_baseline": round(100 * (ai[1] or 0) / bt, 3),
            "rising": sorted(ranked, key=lambda t: -t["lift"])[:10],
            "falling": sorted(ranked, key=lambda t: t["lift"])[:5],
        }
    snap["everywhere"] = _everywhere(c, as_of, meta)
    return snap


def _everywhere(c, as_of, meta, floor=1.15):
    """Topics with lift >= floor on all three sources (each above its volume minimum)."""
    found = None
    for s, cfg in SOURCES.items():
        sub = snapshot_lifts(c, as_of, s, cfg, meta)
        keep = {t for t, (lift, r) in sub.items() if lift and lift >= floor and r >= cfg["min_recent"]}
        found = keep if found is None else found & keep
    return sorted(found)


def snapshot_lifts(c, as_of, s, cfg, meta):
    r0 = as_of - dt.timedelta(days=RECENT - 1)
    b0 = r0 - dt.timedelta(days=BASELINE)
    m = cfg["metric"]
    rt, bt = c.execute(f"SELECT sum({m}) FILTER (WHERE date >= ?), sum({m}) FILTER (WHERE date < ?) FROM sd WHERE source=? AND date>=? AND date<=?",
                       [r0, r0, s, b0, as_of]).fetchone()
    out = {}
    for topic, r, b in c.execute(f"SELECT topic, sum({m}) FILTER (WHERE date >= ?), sum({m}) FILTER (WHERE date < ?) FROM td WHERE source=? AND date>=? AND date<=? GROUP BY topic",
                                 [r0, r0, s, b0, as_of]).fetchall():
        if meta.get(topic, {}).get("group") in SKIP_GROUPS:
            continue
        r, b = r or 0, b or 0
        out[topic] = ((r / rt) / (b / bt) if b else None, r)
    return out


def add_examples(snap, as_of, per_topic=3):
    """Attach the most-voted items behind each rising topic, so readers can check the evidence.

    Needs the local raw cache (data/raw); does nothing without it.
    """
    from tracker.common import raw_path, read_raw
    from tracker.topics import load_topics, match, model_text

    topics = load_topics()
    for s, v in snap["sources"].items():
        wanted = {r["topic"] for r in v["rising"]}
        best = {t: [] for t in wanted}
        seen = set()
        for i in range(RECENT):
            d = as_of - dt.timedelta(days=i)
            if not raw_path(s, d).exists():
                continue
            for row in read_raw(s, d):
                if s == "hn":
                    key = row["url"].split("#")[0].rstrip("/").lower() or row["id"]
                    if key in seen:
                        continue
                    seen.add(key)
                    hits = match(row["title"], topics, require_ai_context=True)
                    item = {"title": row["title"], "url": f"https://news.ycombinator.com/item?id={row['id']}",
                            "score": row["points"], "date": d.isoformat()}
                elif s == "hf_papers":
                    hits = match(row["title"] + "\n" + row["summary"], topics)
                    item = {"title": row["title"], "url": f"https://huggingface.co/papers/{row['id']}",
                            "score": row["upvotes"], "date": d.isoformat()}
                else:
                    hits = match(model_text(row["id"], row["tags"]), topics, machine_text=True)
                    item = {"title": row["id"], "url": f"https://huggingface.co/{row['id']}",
                            "score": row["likes"], "date": d.isoformat()}
                for t in wanted.intersection(hits):
                    best[t].append(item)
        for r in v["rising"]:
            items = sorted(best[r["topic"]], key=lambda x: -x["score"])
            # one example per model owner, so a single uploader can't fill the list
            if s == "hf_models":
                owners, uniq = set(), []
                for x in items:
                    o = x["title"].split("/")[0]
                    if o not in owners:
                        owners.add(o)
                        uniq.append(x)
                items = uniq
            r["examples"] = items[:per_topic]


def monthly(c):
    """Monthly share per source and topic, in each source's counting unit."""
    out = {}
    for s, cfg in SOURCES.items():
        m = cfg["metric"]
        rows = c.execute(f"""
            WITH t AS (SELECT date_trunc('month', date) AS mo, topic, sum({m}) AS v FROM td WHERE source = ? GROUP BY ALL),
                 s AS (SELECT date_trunc('month', date) AS mo, sum({m}) AS tot, count(*) AS days FROM sd WHERE source = ? GROUP BY ALL)
            SELECT strftime(s.mo, '%Y-%m'), t.topic, round(100.0 * t.v / s.tot, 4), t.v, s.tot, s.days
            FROM s JOIN t USING (mo) ORDER BY 1""", [s, s]).fetchall()
        months = sorted({r[0] for r in rows})
        series = {}
        for mo, topic, share, v, tot, days in rows:
            series.setdefault(topic, [None] * len(months))[months.index(mo)] = [share, v]
        totals = dict((r[0], [r[4], r[5]]) for r in rows)
        out[s] = {"months": months, "totals": [totals[mo] for mo in months], "series": series}
    return out


def daily_ai_share(c, as_of, days=90):
    """Daily share of HN stories that mention AI, with a 7-day rolling share."""
    start = as_of - dt.timedelta(days=days + 6)
    rows = c.execute("""
        SELECT s.date, coalesce(t.items, 0), s.items FROM sd s
        LEFT JOIN td t ON t.date = s.date AND t.source = s.source AND t.topic = 'ai_any'
        WHERE s.source = 'hn' AND s.date >= ? AND s.date <= ? ORDER BY 1""", [start, as_of]).fetchall()
    out = []
    for i in range(6, len(rows)):
        win = rows[i - 6:i + 1]
        out.append([rows[i][0].isoformat(), round(100 * sum(r[1] for r in win) / sum(r[2] for r in win), 2),
                    rows[i][1], rows[i][2]])
    return out


def latest_review():
    """Latest Codex review for the page, without the internal verdict line."""
    files = sorted(REVIEWS.glob("*.md")) if REVIEWS.exists() else []
    if not files:
        return None
    text = "\n".join(l for l in files[-1].read_text().splitlines() if not l.lower().startswith("verdict:")).strip()
    return {"date": files[-1].stem[:10], "text": text}


def build(as_of, backfill=0):
    c = con()
    meta = topics_meta(c)
    SNAP.mkdir(exist_ok=True)
    for i in range(backfill, -1, -1):
        d = as_of - dt.timedelta(days=i)
        p = SNAP / f"{d.isoformat()}.json"
        # Past snapshots are frozen. Today's is rewritten on local reruns, but not in CI,
        # which has no raw cache and so could not rebuild the example items.
        if not p.exists() or (i == 0 and not os.environ.get("CI")):
            snap = snapshot(c, d, meta)
            if i == 0:
                add_examples(snap, d)
            p.write_text(json.dumps(snap, indent=1))
    snaps = [json.loads(p.read_text()) for p in sorted(SNAP.glob("*.json"))]
    payload = {
        "as_of": as_of.isoformat(),
        "built_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "sources": SOURCES,
        "topics": meta,
        "snapshots": snaps,
        "monthly": monthly(c),
        "ai_daily": daily_ai_share(c, as_of),
        "review": latest_review(),
        "totals": dict(zip(["items", "first_day", "topics"], c.execute(
            "SELECT sum(items), min(date)::VARCHAR, (SELECT count(*) - 1 FROM tp) FROM sd").fetchone())),
    }
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "data").mkdir(parents=True)
    for f in ["topic_daily.csv", "source_daily.csv", "share_of_voice_monthly.csv", "rising_topics.csv"]:
        if (ROOT / "data" / f).exists():
            shutil.copy(ROOT / "data" / f, OUT / "data" / f)
    shutil.copy(ROOT / "topics.csv", OUT / "data" / "topics.csv")
    if (ROOT / "site" / "og.png").exists():
        shutil.copy(ROOT / "site" / "og.png", OUT / "og.png")
    html = (ROOT / "site" / "template.html").read_text()
    blob = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    (OUT / "index.html").write_text(html.replace("/*__DATA__*/null", blob))
    (OUT / ".nojekyll").write_text("")
    print(f"built _site/ as of {as_of} with {len(snaps)} snapshots")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", type=dt.date.fromisoformat)
    ap.add_argument("--backfill", type=int, default=0)
    a = ap.parse_args()
    if not a.as_of:
        with open(ROOT / "data" / "source_daily.csv") as f:
            a.as_of = max(dt.date.fromisoformat(r["date"]) for r in csv.DictReader(f))
    build(a.as_of, a.backfill)
