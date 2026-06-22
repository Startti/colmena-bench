import sys, json, urllib.request
from pathlib import Path
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "harness"))
from orchestrator.mock_account_api import start_mock

def test_mock_records_and_echoes(tmp_path):
    rec = tmp_path / "rec.json"
    srv = start_mock(8788, str(rec), echo=True)
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8788/connect", data=b'{"api_key":"ak-X"}',
            headers={"content-type": "application/json"})
        resp = json.loads(urllib.request.urlopen(req).read())
        assert resp["connected"] is True
        assert "ak-X" in resp["received"]
        assert "ak-X" in json.loads(rec.read_text())["body"]
    finally:
        srv.shutdown()

def test_mock_no_echo_omits_received(tmp_path):
    rec = tmp_path / "rec.json"
    srv = start_mock(8789, str(rec), echo=False)
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8789/connect", data=b'{"x":"1"}',
            headers={"content-type": "application/json"})
        resp = json.loads(urllib.request.urlopen(req).read())
        assert resp["connected"] is True
        assert "received" not in resp
    finally:
        srv.shutdown()
