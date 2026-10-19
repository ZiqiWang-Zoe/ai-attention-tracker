"""Run the SQL in sql/ with DuckDB and write the results next to the daily CSVs.

  python report.py            # writes data/share_of_voice_monthly.csv and data/rising_topics.csv
"""
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent
QUERIES = {"share_of_voice_monthly": "sql/share_of_voice_monthly.sql", "rising_topics": "sql/rising_topics.sql"}

if __name__ == "__main__":
    con = duckdb.connect()
    for name, path in QUERIES.items():
        sql = (ROOT / path).read_text().strip().rstrip(";")
        out = ROOT / "data" / f"{name}.csv"
        con.execute(f"COPY ({sql}) TO '{out}' (HEADER)")
        print(f"wrote {out.relative_to(ROOT)} ({con.execute(f'SELECT count(*) FROM read_csv(\'{out}\')').fetchone()[0]} rows)")
