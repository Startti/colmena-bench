import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))
REPO = PKG.parent.parent

from bench_common.datasets import read_csv_text, load_orders_sqlite  # noqa: E402

CSV = REPO / "data/orders_synthetic/seeds/S.csv"


def test_read_csv_text_has_header_and_rows():
    text = read_csv_text(CSV)
    assert text.startswith("order_id,customer_id,")
    assert len(text.splitlines()) == 501  # header + 500 rows


def test_load_orders_sqlite_counts_rows():
    conn, run_sql = load_orders_sqlite(CSV)
    out = run_sql("SELECT COUNT(*) AS n FROM orders")
    assert "500" in out
    conn.close()


def test_run_sql_typed_aggregate():
    conn, run_sql = load_orders_sqlite(CSV)
    out = run_sql("SELECT COUNT(*) AS n FROM orders WHERE status='cancelled'")
    assert out.strip() != ""
    conn.close()


def test_run_sql_bad_query_returns_error_string():
    conn, run_sql = load_orders_sqlite(CSV)
    out = run_sql("SELECT * FROM nonexistent")
    assert out.startswith("ERROR:")
    conn.close()
