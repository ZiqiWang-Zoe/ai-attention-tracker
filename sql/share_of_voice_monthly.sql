-- Share of voice by topic, source and month.
-- share_pct = items matching the topic / all items from that source that month.
-- Months where a topic had no matches are filled with 0 so charts don't skip them.
-- Run from the repo root:  .venv/bin/python report.py   (or paste into any DuckDB shell)

WITH topic_month AS (
    SELECT date_trunc('month', date)::DATE AS month, source, topic,
           sum(items) AS items, sum(points) AS points
    FROM read_csv('data/topic_daily.csv', types = {'authors': 'VARCHAR'})
    GROUP BY ALL
),
source_month AS (
    SELECT date_trunc('month', date)::DATE AS month, source,
           sum(items) AS total_items, sum(points) AS total_points,
           count(*) AS days_covered
    FROM read_csv('data/source_daily.csv', types = {'authors': 'VARCHAR'})
    GROUP BY ALL
),
topics AS (
    SELECT topic, "group", label
    FROM read_csv('topics.csv', all_varchar = true)
)
SELECT
    s.month,
    s.source,
    t."group" AS topic_group,
    t.topic,
    t.label,
    coalesce(tm.items, 0)                                   AS items,
    s.total_items,
    round(100.0 * coalesce(tm.items, 0) / s.total_items, 3) AS share_pct,
    coalesce(tm.points, 0)                                  AS points,
    round(100.0 * coalesce(tm.points, 0) / nullif(s.total_points, 0), 3) AS points_share_pct,
    s.days_covered
FROM source_month s
CROSS JOIN topics t
LEFT JOIN topic_month tm
       ON tm.month = s.month AND tm.source = s.source AND tm.topic = t.topic
ORDER BY s.month, s.source, share_pct DESC;
