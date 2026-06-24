"""Process-tree RSS + CPU sampler for the load-test.

Reports the full RAM-over-time curve (not just peak) and CPU-seconds, so we can
compute mean/peak/area-under-curve RAM and CPU-per-request. Samples in a daemon
thread; subtract idle baseline downstream to get marginal RAM-per-session.
"""
from __future__ import annotations

import threading
import time
from typing import Any

import psutil


class ResourceSampler:
    def __init__(self, pid: int, interval: float = 0.1) -> None:
        self.pid = pid
        self.interval = interval
        self.series: list[dict[str, float]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._t0 = 0.0

    def _tree(self) -> list[psutil.Process]:
        try:
            proc = psutil.Process(self.pid)
        except psutil.NoSuchProcess:
            return []
        procs = [proc]
        try:
            procs.extend(proc.children(recursive=True))
        except psutil.NoSuchProcess:
            pass
        return procs

    def _sample_once(self) -> dict[str, float] | None:
        procs = self._tree()
        if not procs:
            return None
        rss = 0
        cpu = 0.0
        for p in procs:
            try:
                rss += p.memory_info().rss
                ct = p.cpu_times()
                cpu += ct.user + ct.system
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return {"t": time.time() - self._t0, "rss_bytes": float(rss), "cpu_seconds": cpu}

    def _run(self) -> None:
        while not self._stop.is_set():
            s = self._sample_once()
            if s is not None:
                self.series.append(s)
            self._stop.wait(self.interval)

    def start(self) -> None:
        self._t0 = time.time()
        self._stop.clear()
        self.series = []
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def summarize(self) -> dict[str, Any]:
        if not self.series:
            return {"samples": 0, "rss_peak_bytes": 0, "rss_mean_bytes": 0,
                    "rss_auc_bytes_s": 0.0, "cpu_seconds": 0.0}
        rss = [s["rss_bytes"] for s in self.series]
        # trapezoidal area under the RSS-vs-time curve
        auc = 0.0
        for a, b in zip(self.series, self.series[1:]):
            auc += (a["rss_bytes"] + b["rss_bytes"]) / 2.0 * (b["t"] - a["t"])
        cpu_seconds = self.series[-1]["cpu_seconds"] - self.series[0]["cpu_seconds"]
        return {
            "samples": len(self.series),
            "rss_peak_bytes": max(rss),
            "rss_mean_bytes": sum(rss) / len(rss),
            "rss_auc_bytes_s": auc,
            "cpu_seconds": max(0.0, cpu_seconds),
        }
