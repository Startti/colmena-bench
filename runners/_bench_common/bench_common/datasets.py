"""Dataset helpers shared by runners: CSV-as-text (naive) and SQLite (expert)."""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Callable


def read_csv_text(csv_path: Path | str) -> str:
    return Path(csv_path).read_text(encoding="utf-8")


def load_orders_sqlite(csv_path: Path | str) -> tuple[sqlite3.Connection, Callable[[str], str]]:
    """Load the CSV into an in-memory table `orders`. Returns (conn, run_sql).

    `run_sql(query)` runs a SELECT and returns a compact text table (header +
    rows), or an `ERROR: ...` string the agent can read and recover from. All
    columns are stored as TEXT; SQL CAST as needed for math.
    """
    path = Path(csv_path)
    conn = sqlite3.connect(":memory:")
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        cols = ", ".join(f'"{c}" TEXT' for c in header)
        conn.execute(f"CREATE TABLE orders ({cols})")
        placeholders = ", ".join("?" for _ in header)
        conn.executemany(f"INSERT INTO orders VALUES ({placeholders})", reader)
    conn.commit()

    def run_sql(query: str) -> str:
        try:
            cur = conn.execute(query)
        except Exception as e:  # noqa: BLE001 — surface to the agent, don't crash
            return f"ERROR: {type(e).__name__}: {e}"
        rows = cur.fetchall()
        names = [d[0] for d in cur.description] if cur.description else []
        lines = [" | ".join(names)] if names else []
        for r in rows[:200]:  # cap output so a bad query can't blow up tokens
            lines.append(" | ".join("" if v is None else str(v) for v in r))
        if len(rows) > 200:
            lines.append(f"... ({len(rows)} rows total, showing 200)")
        return "\n".join(lines) if lines else "(no rows)"

    return conn, run_sql
