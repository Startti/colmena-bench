import json
from fastapi.testclient import TestClient
from harness.loadtest.stub_llm import build_app


def _client(delay_ms=0):
    return TestClient(build_app(delay_ms=delay_ms))


def test_first_call_returns_tool_call():
    c = _client()
    r = c.post("/v1/chat/completions", json={
        "model": "gemini-2.5-flash",
        "messages": [{"role": "user", "content": "count orders"}],
    })
    assert r.status_code == 200
    body = r.json()
    msg = body["choices"][0]["message"]
    assert body["choices"][0]["finish_reason"] == "tool_calls"
    assert msg["tool_calls"][0]["function"]["name"] == "run_sql"
    args = json.loads(msg["tool_calls"][0]["function"]["arguments"])
    assert "query" in args


def test_followup_with_tool_result_returns_final():
    c = _client()
    r = c.post("/v1/chat/completions", json={
        "model": "gemini-2.5-flash",
        "messages": [
            {"role": "user", "content": "count orders"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_1", "type": "function",
                 "function": {"name": "run_sql", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "call_1", "content": "1000"},
        ],
    })
    body = r.json()
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["choices"][0]["message"]["content"]
    assert not body["choices"][0]["message"].get("tool_calls")


def test_tool_endpoint_returns_constant():
    c = _client()
    r = c.post("/tool", json={"query": "SELECT count(*) FROM orders"})
    assert r.status_code == 200
    assert r.json()["result"] == "1000"
