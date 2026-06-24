from harness.loadtest.aggregate import compute_metrics


def test_compute_metrics():
    levels = [
        {"concurrency": 1, "throughput_rps": 1.6, "p95_ms": 620, "completed": 96,
         "errors": 0, "rss_mean_bytes": 60_000_000, "cpu_seconds": 0.5},
        {"concurrency": 4, "throughput_rps": 6.2, "p95_ms": 650, "completed": 372,
         "errors": 0, "rss_mean_bytes": 72_000_000, "cpu_seconds": 1.8},
        {"concurrency": 16, "throughput_rps": 9.0, "p95_ms": 1700, "completed": 540,
         "errors": 3, "rss_mean_bytes": 120_000_000, "cpu_seconds": 6.0},
    ]
    m = compute_metrics(levels, idle_rss_bytes=50_000_000)
    assert m["throughput_ceiling_rps"] == 9.0
    # useful concurrency: largest C with p95 <= 2*baseline(620)=1240 -> C=4
    assert m["useful_concurrency"] == 4
    # rss/session at C=16: (120M-50M)/16
    assert abs(m["rss_per_session_bytes"]["16"] - (70_000_000 / 16)) < 1
    # cpu/request at C=16: 6.0/540
    assert abs(m["cpu_per_request_s"]["16"] - (6.0 / 540)) < 1e-6
    assert m["saturation_concurrency"] == 16  # first level with errors>0
