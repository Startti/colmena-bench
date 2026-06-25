import threading
import time
import uvicorn
from harness.loadtest.stub_llm import build_app
from harness.loadtest import driver


class _Server:
    def __init__(self, app, port):
        self.config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        self.server = uvicorn.Server(self.config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                break
            time.sleep(0.05)
        return self

    def __exit__(self, *a):
        self.server.should_exit = True
        self.thread.join(timeout=3)


def test_driver_reports_throughput_and_latency():
    port = 9211
    # delay 50ms per call; /tool path returns instantly
    with _Server(build_app(delay_ms=50), port):
        result = driver.run_level(
            url=f"http://127.0.0.1:{port}/tool",
            payload={"query": "x"},
            concurrency=4,
            duration_s=1.0,
        )
    assert result["concurrency"] == 4
    assert result["completed"] > 0
    assert result["throughput_rps"] > 0
    assert result["p50_ms"] >= 0
    assert result["p95_ms"] >= result["p50_ms"]
    assert result["errors"] == 0
