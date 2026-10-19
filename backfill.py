"""Collect raw data for a date range, then rebuild the daily CSVs.

  python backfill.py --start 2025-01-01 --end 2026-10-17
  python backfill.py --sources hn --start 2026-10-01      # one source
  python backfill.py --refresh-days 7                       # re-fetch the last 7 days
  python backfill.py --aggregate-only                       # after editing topics.csv

Days already in data/raw are skipped, so the command can be stopped and re-run.
Dates are UTC. The default end is yesterday, the last complete day.
"""
import argparse
import datetime as dt
import sys
from concurrent.futures import ThreadPoolExecutor

from tracker import aggregate, hf, hn
from tracker.common import days, raw_path, write_raw

FETCHERS = {"hn": hn.fetch_day, "hf_papers": hf.fetch_papers, "hf_models": hf.fetch_models}


def collect(source, start, end, refresh_from):
    fetch = FETCHERS[source]
    done = 0
    for day in days(start, end):
        if raw_path(source, day).exists() and day < refresh_from:
            continue
        write_raw(source, day, list(fetch(day)))
        done += 1
        if done % 25 == 0:
            print(f"{source}: through {day}", flush=True)
    print(f"{source}: fetched {done} days", flush=True)


def main():
    yesterday = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=dt.date.fromisoformat, default=dt.date(2025, 1, 1))
    ap.add_argument("--end", type=dt.date.fromisoformat, default=yesterday)
    ap.add_argument("--sources", nargs="+", default=list(FETCHERS), choices=list(FETCHERS))
    ap.add_argument("--refresh-days", type=int, default=0, help="re-fetch this many most recent days")
    ap.add_argument("--aggregate-only", action="store_true")
    args = ap.parse_args()

    if not args.aggregate_only:
        refresh_from = args.end - dt.timedelta(days=args.refresh_days - 1) if args.refresh_days else dt.date.max
        # Sources live on different hosts (or are rate limited separately), so run them side by side.
        with ThreadPoolExecutor(len(args.sources)) as ex:
            futures = [ex.submit(collect, s, args.start, args.end, refresh_from) for s in args.sources]
            for f in futures:
                f.result()
    n = aggregate.build()
    print(f"aggregated {n} source-days into data/topic_daily.csv and data/source_daily.csv")


if __name__ == "__main__":
    sys.exit(main())
