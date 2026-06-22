import json
import spans_callback as sc

def test_scan_messages_for_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("BENCH_MASK_AUDIT_SECRET", "sk-live-REFUND-SECRET-abc123")
    monkeypatch.setenv("LITELLM_SPANS_DIR", str(tmp_path))
    msgs = [{"role": "user", "content": "here is the key sk-live-REFUND-SECRET-abc123"}]
    sc.audit_messages_for_secret(msgs, run_id="r1")
    rec = json.loads((tmp_path / "mask-r1.json").read_text())
    assert rec["secret_leaked"] is True

def test_no_leak_records_false(tmp_path, monkeypatch):
    monkeypatch.setenv("BENCH_MASK_AUDIT_SECRET", "sk-live-REFUND-SECRET-abc123")
    monkeypatch.setenv("LITELLM_SPANS_DIR", str(tmp_path))
    sc.audit_messages_for_secret([{"role": "user", "content": "handle <sv_x>"}], run_id="r2")
    rec = json.loads((tmp_path / "mask-r2.json").read_text())
    assert rec["secret_leaked"] is False

def test_sticky_true_once_leaked(tmp_path, monkeypatch):
    monkeypatch.setenv("BENCH_MASK_AUDIT_SECRET", "sk-live-REFUND-SECRET-abc123")
    monkeypatch.setenv("LITELLM_SPANS_DIR", str(tmp_path))
    sc.audit_messages_for_secret([{"role": "user", "content": "sk-live-REFUND-SECRET-abc123"}], run_id="r3")
    sc.audit_messages_for_secret([{"role": "user", "content": "clean now"}], run_id="r3")
    rec = json.loads((tmp_path / "mask-r3.json").read_text())
    assert rec["secret_leaked"] is True   # stays True after first leak

def test_noop_when_env_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("BENCH_MASK_AUDIT_SECRET", raising=False)
    monkeypatch.setenv("LITELLM_SPANS_DIR", str(tmp_path))
    sc.audit_messages_for_secret([{"role": "user", "content": "anything"}], run_id="r4")
    assert not (tmp_path / "mask-r4.json").exists()   # no file when audit disabled
