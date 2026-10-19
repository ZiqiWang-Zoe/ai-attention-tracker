"""Load topics.csv and match text to topics.

Matching is regex-based and multi-label: one item can count toward several topics.
Patterns are case-insensitive except parts wrapped in (?-i:...), which is how short
acronyms like MCP or RAG avoid matching ordinary words.
"""
import csv
import re
from dataclasses import dataclass
from pathlib import Path

TOPICS_CSV = Path(__file__).resolve().parent.parent / "topics.csv"


@dataclass
class Topic:
    topic: str
    group: str
    label: str
    needs_ai_context: bool
    include: re.Pattern
    exclude: re.Pattern | None
    include_lower: re.Pattern  # for lowercase machine text (HF model ids and tags)
    exclude_lower: re.Pattern | None


def _compile(pattern, lower=False):
    if not pattern:
        return None
    if lower:
        # Model ids and tags are mostly lowercase, so case-sensitive acronym guards
        # would miss them. Drop the guard and match case-insensitively.
        pattern = pattern.replace("(?-i:", "(?:")
    return re.compile(pattern, re.IGNORECASE)


def load_topics(path=TOPICS_CSV):
    topics = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            topics.append(Topic(
                topic=row["topic"],
                group=row["group"],
                label=row["label"],
                needs_ai_context=row["needs_ai_context"].strip() == "yes",
                include=_compile(row["include"]),
                exclude=_compile(row["exclude"]),
                include_lower=_compile(row["include"], lower=True),
                exclude_lower=_compile(row["exclude"], lower=True),
            ))
    return topics


def match(text, topics, require_ai_context=False, machine_text=False):
    """Return the list of topic names that match `text`.

    require_ai_context: for general sources (Hacker News), topics flagged
    needs_ai_context only count when the text also matches ai_any.
    machine_text: use the lowercase-friendly patterns (HF model ids and tags).
    """
    hits = []
    for t in topics:
        inc = t.include_lower if machine_text else t.include
        exc = t.exclude_lower if machine_text else t.exclude
        if inc.search(text) and not (exc and exc.search(text)):
            hits.append(t.topic)
    if require_ai_context and "ai_any" not in hits:
        flagged = {t.topic for t in topics if t.needs_ai_context}
        hits = [h for h in hits if h not in flagged]
    return hits


_SEP = re.compile(r"[-_/.:]+")
# Hub bookkeeping tags that say nothing about the model's topic (and would match
# words like "license" or "inference" on almost every model).
_SKIP_PREFIXES = ("license:", "region:", "deploy:", "dataset:", "arxiv:", "doi:")
_SKIP_TAGS = {"endpoints_compatible", "text-generation-inference", "autotrain_compatible", "has_space", "custom_code"}


def model_text(model_id, tags):
    """Turn an HF model id and its tags into matchable text: 'Qwen/Qwen3-8B-GGUF' -> 'Qwen Qwen3 8B GGUF'."""
    kept = [t for t in tags if t not in _SKIP_TAGS and not t.startswith(_SKIP_PREFIXES)]
    return _SEP.sub(" ", " ".join([model_id, *kept]))
