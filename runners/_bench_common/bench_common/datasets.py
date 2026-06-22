"""Dataset helpers shared by runners: CSV-as-text (naive) and SQLite (expert)."""
from __future__ import annotations

import csv
import sqlite3
import threading
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
    # check_same_thread=False so agents that execute tools on worker threads
    # (LangGraph/LlamaIndex/ADK run tools off the main thread) can reuse the
    # same in-memory connection.  A lock serializes access — sqlite is not
    # safe for concurrent use of one connection.
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    lock = threading.Lock()
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        cols = ", ".join(f'"{c}" TEXT' for c in header)
        conn.execute(f"CREATE TABLE orders ({cols})")
        placeholders = ", ".join("?" for _ in header)
        conn.executemany(f"INSERT INTO orders VALUES ({placeholders})", reader)
    conn.commit()

    def run_sql(query: str) -> str:
        with lock:
            try:
                cur = conn.execute(query)
                rows = cur.fetchall()
                names = [d[0] for d in cur.description] if cur.description else []
            except Exception as e:  # noqa: BLE001 — surface to the agent, don't crash
                return f"ERROR: {type(e).__name__}: {e}"
        lines = [" | ".join(names)] if names else []
        for r in rows[:200]:  # cap output so a bad query can't blow up tokens
            lines.append(" | ".join("" if v is None else str(v) for v in r))
        if len(rows) > 200:
            lines.append(f"... ({len(rows)} rows total, showing 200)")
        return "\n".join(lines) if lines else "(no rows)"

    return conn, run_sql
