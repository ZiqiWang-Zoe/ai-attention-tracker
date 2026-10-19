"""Hugging Face collectors.

daily_papers: the papers featured on huggingface.co/papers for a date (title,
abstract, upvotes).

models: every public model created on a UTC day. The models list is sorted by
creation time and paged with a cursor on the MongoDB _id, whose first four bytes
are a Unix timestamp. That lets us jump straight to the end of any day instead of
paging from today backward.
"""
import base64
import datetime as dt
import json
import re

from .common import get

PAPERS_URL = "https://huggingface.co/api/daily_papers"
MODELS_URL = "https://huggingface.co/api/models"


def fetch_papers(day: dt.date):
    for item in get(PAPERS_URL, {"date": day.isoformat()}).json():
        p = item["paper"]
        yield {
            "id": p["id"],
            "title": p.get("title") or item.get("title") or "",
            "summary": p.get("summary") or item.get("summary") or "",
            "upvotes": p.get("upvotes") or 0,
        }


def _cursor_before(ts):
    oid = format(int(ts), "08x") + "0" * 16
    return base64.b64encode(json.dumps({"_id": {"$lt": oid}}, separators=(",", ":")).encode()).decode()


_NEXT = re.compile(r"<([^>]+)>;\s*rel=\"next\"")


def fetch_models(day: dt.date):
    start = dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc)
    end = start + dt.timedelta(days=1)
    lo, hi = start.isoformat()[:10], end.isoformat()[:10]
    params = {"sort": "createdAt", "direction": -1, "limit": 1000, "cursor": _cursor_before(end.timestamp())}
    url = MODELS_URL
    while True:
        r = get(url, params)
        page = r.json()
        for m in page:
            created = (m.get("createdAt") or "")[:10]
            if lo <= created < hi:
                yield {
                    "id": m["id"],
                    "tags": m.get("tags") or [],
                    "likes": m.get("likes") or 0,
                    "downloads": m.get("downloads") or 0,
                    "createdAt": m.get("createdAt"),
                }
        if not page or (page[-1].get("createdAt") or "")[:10] < lo:
            return
        nxt = _NEXT.search(r.headers.get("Link", ""))
        if not nxt:
            return
        url, params = nxt.group(1), None
