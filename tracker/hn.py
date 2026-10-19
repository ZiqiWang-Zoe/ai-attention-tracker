"""Hacker News collector (Algolia search API).

Fetches every story submitted on a UTC day, not just AI stories, so the daily total
is a fair denominator for share of voice. Algolia returns at most 1,000 hits per
query, so busy windows are split in half until each piece fits.
"""
import datetime as dt

from .common import get

SOURCE = "hn"
URL = "https://hn.algolia.com/api/v1/search_by_date"
FIELDS = "title,url,points,num_comments,author,created_at_i"


def _window(a, b):
    params = {
        "tags": "story",
        "numericFilters": f"created_at_i>={a},created_at_i<{b}",
        "hitsPerPage": 1000,
        "attributesToRetrieve": FIELDS,
        "attributesToHighlight": "",
    }
    j = get(URL, params).json()
    if j["nbHits"] > len(j["hits"]) and b - a > 60:
        mid = (a + b) // 2
        return _window(a, mid) + _window(mid, b)
    return j["hits"]


def fetch_day(day: dt.date):
    a = int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc).timestamp())
    hits = _window(a, a + 86400)
    seen = set()
    for h in hits:
        if h["objectID"] in seen:
            continue
        seen.add(h["objectID"])
        yield {
            "id": h["objectID"],
            "title": h.get("title") or "",
            "url": h.get("url") or "",
            "points": h.get("points") or 0,
            "comments": h.get("num_comments") or 0,
            "author": h.get("author") or "",
        }
