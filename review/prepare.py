"""Write _review/input.md: the evidence Codex reads for the daily data check.

  python review/prepare.py

Contains daily totals for the last 21 days (to spot broken collection), today's
snapshot, the largest day-over-day share moves, and sample matched titles for the
top risers on each source (to spot bad keyword matches). Uses the raw cache, so it
runs after backfill.py on the same machine.
"""
import csv
import datetime as dt
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tracker.common import raw_path, read_raw  # noqa: E402
from tracker.topics import load_topics, match, model_text  # noqa: E402

OUT = ROOT / "_review"


def main():
    with open(ROOT / "data" / "source_daily.csv") as f:
        totals = list(csv.DictReader(f))
    last = max(dt.date.fromisoformat(r["date"]) for r in totals)
    snap = json.loads((ROOT / "snapshots" / f"{last}.json").read_text())
    prev_p = ROOT / "snapshots" / f"{last - dt.timedelta(days=1)}.json"
    prev = json.loads(prev_p.read_text()) if prev_p.exists() else None
    topics = load_topics()
    label = {t.topic: t.label for t in topics}
    tobj = {t.topic: t for t in topics}

    lines = [f"# Daily data check input for {last}", ""]
    lines += ["## Daily totals, last 21 days", "", "| date | source | items | points | authors |", "|---|---|---|---|---|"]
    since = last - dt.timedelta(days=20)
    for r in totals:
        if dt.date.fromisoformat(r["date"]) >= since:
            lines.append(f"| {r['date']} | {r['source']} | {r['items']} | {r['points']} | {r['authors']} |")

    lines += ["", "## Today's snapshot (last 30 days vs prior 90)", ""]
    for s, v in snap["sources"].items():
        lines.append(f"### {s}  (recent total {v['recent_total']}, baseline total {v['baseline_total']}, AI share {v['ai_share_recent']}% vs {v['ai_share_baseline']}%)")
        for r in v["rising"]:
            lines.append(f"- {r['topic']} ({label.get(r['topic'], '')}): {r['baseline_share']}% -> {r['recent_share']}%, lift {r['lift']}, recent {r['recent']}, baseline {r['baseline']}")
        lines.append("")
    lines.append(f"Rising on all three sources: {', '.join(snap['everywhere']) or 'none'}")

    if prev:
        lines += ["", "## Changes since yesterday's snapshot", ""]
        for s in snap["sources"]:
            a = [r["topic"] for r in prev["sources"][s]["rising"][:5]]
            b = [r["topic"] for r in snap["sources"][s]["rising"][:5]]
            lines.append(f"- {s}: yesterday top 5 {a}; today top 5 {b}")

    lines += ["", "## Sample matched items for today's top risers (random, up to 8 each, last 7 days)", ""]
    random.seed(str(last))
    for s, v in snap["sources"].items():
        for r in v["rising"][:4]:
            t = r["topic"]
            pool = []
            for i in range(7):
                d = last - dt.timedelta(days=i)
                if not raw_path(s, d).exists():
                    continue
                for row in read_raw(s, d):
                    if s == "hn":
                        text, hit = row["title"], t in match(row["title"], topics, require_ai_context=True)
                    elif s == "hf_papers":
                        full = row["title"] + "\n" + row["summary"]
                        hit = t in match(full, topics)
                        m = tobj[t].include.search(full) if hit else None
                        snippet = full[max(0, m.start() - 70):m.end() + 70].replace("\n", " ") if m else ""
                        text = f"{row['title']}  [matched: \"{m.group(0) if m else ''}\" in: ...{snippet}...]"
                    else:
                        text = row["id"] + "  tags: " + ", ".join(row["tags"][:12])
                        hit = t in match(model_text(row["id"], row["tags"]), topics, machine_text=True)
                    if hit:
                        pool.append(text)
            lines.append(f"### {s} / {t}  ({len(pool)} matches in 7 days)")
            for x in random.sample(pool, min(8, len(pool))):
                lines.append(f"- {x[:400]}")
            lines.append("")

    OUT.mkdir(exist_ok=True)
    (OUT / "input.md").write_text("\n".join(lines) + "\n")
    print(f"wrote _review/input.md for {last}")


if __name__ == "__main__":
    main()
