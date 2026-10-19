-- Rising topics: share of voice in the last 30 days vs the 90 days before that.
-- One row per source and topic. lift = recent share / baseline share.
-- Topics need at least 20 matching items in the recent window to be ranked,
-- so a jump from 1 item to 3 doesn't top the list.

WITH bounds AS (
    SELECT max(date) AS last_day FROM read_csv('data/source_daily.csv', types = {'authors': 'VARCHAR'})
),
windowed AS (
    SELECT source, topic, items,
           CASE WHEN date >  last_day - INTERVAL 30 DAY THEN 'recent'
                WHEN date >  last_day - INTERVAL 120 DAY THEN 'baseline' END AS win
    FROM read_csv('data/topic_daily.csv', types = {'authors': 'VARCHAR'}), bounds
),
totals AS (
    SELECT source,
           sum(items) FILTER (WHERE date >  last_day - INTERVAL 30 DAY) AS recent_total,
           sum(items) FILTER (WHERE date <= last_day - INTERVAL 30 DAY
                                AND date >  last_day - INTERVAL 120 DAY) AS baseline_total
    FROM read_csv('data/source_daily.csv', types = {'authors': 'VARCHAR'}), bounds
    GROUP BY source
),
counts AS (
    SELECT source, topic,
           sum(items) FILTER (WHERE win = 'recent')   AS recent_items,
           sum(items) FILTER (WHERE win = 'baseline') AS baseline_items
    FROM windowed WHERE win IS NOT NULL
    GROUP BY ALL
)
SELECT
    c.source,
    c.topic,
    coalesce(c.recent_items, 0)   AS recent_items,
    coalesce(c.baseline_items, 0) AS baseline_items,
    round(100.0 * coalesce(c.recent_items, 0)   / t.recent_total, 3)   AS recent_share_pct,
    round(100.0 * coalesce(c.baseline_items, 0) / t.baseline_total, 3) AS baseline_share_pct,
    round((coalesce(c.recent_items, 0) / t.recent_total)
          / nullif(coalesce(c.baseline_items, 0) / t.baseline_total, 0), 2) AS lift
FROM counts c JOIN totals t USING (source)
WHERE coalesce(c.recent_items, 0) >= 20 AND c.topic <> 'ai_any'
ORDER BY c.source, lift DESC NULLS FIRST;
