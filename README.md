# AI Attention Tracker

Where is AI attention going, and who notices first? This project counts how often 59 AI topics show up on public sources each day, then reports each topic as a share of everything that source published. Shares, not raw counts, because every source grows over time.

Week 1 covers Hacker News and Hugging Face, daily from 2025-01-01. arXiv and GitHub come next.

## Sources

| Source key | What one item is | Text matched | Daily total (denominator) |
|---|---|---|---|
| `hn` | A Hacker News story | Title | All stories submitted that UTC day, AI or not |
| `hf_papers` | A paper featured on huggingface.co/papers | Title and abstract | All featured papers that day |
| `hf_models` | A public model created on the Hugging Face Hub | Model id and tags | All public models created that UTC day |

All three are public APIs that need no login: the Algolia HN Search API, `huggingface.co/api/daily_papers` and `huggingface.co/api/models`.

## Coverage (backfill of 2026-10-18)

| Source | Days | Items | Average per day |
|---|---|---|---|
| `hn` | 655 (2025-01-01 to 2026-10-17) | 595,958 stories | 910 |
| `hf_papers` | 655 | 13,482 papers | 21 (none on most weekends) |
| `hf_models` | 655 | 2,004,819 models | 3,061 |

## Output files

| File | Grain | Columns |
|---|---|---|
| `data/topic_daily.csv` | topic x source x day | `date, source, topic, items, points, authors` |
| `data/source_daily.csv` | source x day | `date, source, items, points, authors` |
| `data/share_of_voice_monthly.csv` | topic x source x month | items, source total, share %, points share % |
| `data/rising_topics.csv` | topic x source | share in the last 30 days vs the 90 days before, and the lift |

- `items`: stories, papers or models that matched the topic (or, in `source_daily`, the day's total).
- `points`: HN points, paper upvotes or model likes, as of the day the data was collected.
- `authors`: distinct HN submitters or distinct model owners. Blank for papers.
- Share of voice = topic `items` / source `items` for the same period. Days with no match are absent from `topic_daily`; the monthly SQL fills them with 0.

## Method

1. Collect every item for each day, not only AI items, so the denominator is honest. Raw rows are cached in `data/raw/` (not committed) so the topic list can change without downloading again.
2. Match each item against `topics.csv`. Each topic is a regular expression with an optional exclude pattern. Matching is case-insensitive, except short acronyms (MCP, RAG, MoE, LoRA) which must be upper case in titles and abstracts so they don't match ordinary words. One item can count toward several topics.
3. On Hacker News, which covers far more than AI, topics flagged `needs_ai_context` only count if the title also matches the broad `ai_any` topic. This keeps "medical", "reasoning" or "benchmark" stories about other subjects out.
4. For models, Hub bookkeeping tags such as `license:*` and `endpoints_compatible` are ignored, and model ids are split on `-_/.:` so `Qwen3-8B-GGUF` reads as `Qwen3 8B GGUF`.
5. Aggregate by day, then month in DuckDB (`sql/`).

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python backfill.py                       # 2025-01-01 to yesterday, skips days already cached
.venv/bin/python backfill.py --refresh-days 7      # re-fetch the last week (points and model tags settle late)
.venv/bin/python backfill.py --aggregate-only      # after editing topics.csv
.venv/bin/python report.py                         # monthly share of voice and rising topics
```

A full backfill takes about 25 minutes, mostly Hugging Face's limit of 500 requests per 5 minutes.

## Limits

- **Keyword matching is blunt.** It misses items that discuss a topic without its keywords and catches some that use a keyword in another sense ("Claude de France", a job listing that mentions an LLM). Spot checks on HN titles look mostly clean, but nobody has hand-labeled a sample yet, so treat precision as unknown.
- **HN titles are short.** A story about agents titled "We rebuilt our support flow" does not count as agents. Shares on HN understate every topic equally, which matters less for trends than for levels.
- **Hugging Face models are noisy.** Many uploads are automated checkpoints, course exercises or quantized copies of one popular model. A single account can upload hundreds in a day. The `authors` column (distinct owners) is a sturdier signal than `items` for models.
- **Model tags are architecture tags.** A model tagged `llama` uses the Llama architecture, which many non-Meta models do, so `meta_llama` on `hf_models` means "Llama-family" rather than "made by Meta". The same holds for fine-tunes whose `base_model` tag names another lab's model.
- **Recent days are incomplete for models.** The Hub adds most tags after an upload is processed, so the last few days undercount topic matches until a refresh.
- **Words mean different things in research.** "Policy" in a paper abstract is usually a reinforcement learning policy, so the regulation topic only counts phrases like "AI policy" or "public policy". Expect more cases like this as the topic list is reviewed.
- **Points and likes are as of collection,** not as of the day posted. Older items have had longer to collect votes.
- **Deleted and private items are gone.** Models removed since upload cannot be counted.
- **Hugging Face daily papers are curated** by the Hub team and the community, about 20 to 60 a weekday and few or none on weekends. That makes monthly figures more reliable than daily ones for this source.
- **Correlation only.** A rise in share means more people wrote or uploaded about a topic. It does not say why.

## Layout

```
backfill.py              collect + aggregate CLI
report.py                runs sql/ and writes the monthly and rising CSVs
topics.csv               topic list v1: name, group, label, AI-context flag, include and exclude regex
tracker/hn.py            Hacker News collector
tracker/hf.py            Hugging Face daily papers and models collectors
tracker/topics.py        matching rules
tracker/aggregate.py     raw cache -> daily CSVs
sql/                     DuckDB queries
data/                    published CSVs (raw cache is git-ignored)
```
