import os
import time
from harness.loadtest.sampler import ResourceSampler


def test_sampler_collects_series_and_summary():
    sampler = ResourceSampler(pid=os.getpid(), interval=0.02)
    sampler.start()
    # busy a little so CPU time advances and time passes
    end = time.time() + 0.3
    x = 0
    while time.time() < end:
        x += 1
    sampler.stop()
    series = sampler.series
    assert len(series) >= 3
    for sample in series:
        assert sample["rss_bytes"] > 0
        assert sample["t"] >= 0
    summary = sampler.summarize()
    assert summary["rss_peak_bytes"] >= summary["rss_mean_bytes"] > 0
    assert summary["rss_auc_bytes_s"] > 0
    assert summary["cpu_seconds"] >= 0.0
    assert summary["samples"] == len(series)
