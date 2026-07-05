"""Task 10 — LangGraph secrets handler (Demo #10): the NAIVE arm.

LangGraph's native durable HITL (``interrupt()`` / ``Command(resume=...)``) lets
you suspend for a human answer, but the resumed value flows straight back into
graph state and into the next LLM call — there is no native OUTBOUND secret
masking. The idiomatic collect-mid-conversation pattern therefore puts the secret
into the LLM transcript. This handler does the simplest idiomatic thing: ask the
user, take the pasted credentials, and run them through the LLM — so the proxy's
leak audit (which scans every LLM request's messages for the secret marker) flags
the leak. Then it POSTs the REAL secret values to the mock connect endpoint, and
makes a final LLM call that includes the mock's response (echo variant -> the
echoed secret also passes through the LLM).

Contrast with Colmena (runners/colmena/runner/tasks/task10_secrets.py), whose
secure_suspend never lets the secret reach the LLM/proxy.

LLM wiring mirrors task06_refund.py, which calls ``_LLM.invoke([HumanMessage(...)])``
on the same proxy-wired LangChain chat model and reads ``.content``. We pass
role/content tuples (the chat model accepts 2-tuples directly).

STEELMAN ARM (``BENCH_LANGGRAPH_ISOLATED=1``) — ``_run_isolated``. LangGraph's
native ``interrupt()`` CAN collect the secret out-of-band: the credentials arrive
via ``Command(resume=...)`` straight into a graph node's LOCAL scope and are POSTed
to the connect endpoint WITHOUT ever entering an LLM message. This is the
hand-architected analog of Colmena's ``secure_suspend`` — same 0%-leak outcome, but
you must (a) route collection through the interrupt channel instead of the chat
transcript and (b) hand-write the outbound scrub for the echo variant (Colmena
re-masks the tool response for you). It proves the demo10 claim is "Colmena does
declaratively what LangGraph makes you hand-wire", not "only Colmena can".

Handler contract: ``run(task_def, llm, args) -> (answer, usage, extras)``.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, TypedDict

from bench_common import RunnerArgs
from bench_common import scenario_secrets as ss


def _ask(llm: Any, msgs: list[tuple[str, str]]) -> str:
    """One LLM call over role/content tuples (same proxy-wired chat model and
    ``.invoke(...).content`` idiom as task06_refund's ``_LLM.invoke``). The secret
    values live in ``msgs`` so the proxy audit sees them."""
    return str(llm.invoke(msgs).content)


def _ask_best_effort(llm: Any, msgs: list[tuple[str, str]]) -> str:
    """The leak fires on the REQUEST (proxy audits request messages); a transient
    empty/malformed completion must NOT sink the cell. Retry a few times, then
    tolerate failure by returning ''."""
    last = None
    for _ in range(3):
        try:
            return _ask(llm, msgs)
        except Exception as e:  # noqa: BLE001 — transient empty completions
            last = e
    return ""


_SECRET_KEYS = ("api_key", "api_secret", "webhook_signing_secret")


class _IsoState(TypedDict, total=False):
    status: str
    resp: str  # connect-endpoint response, ALREADY scrubbed of secret values


def _post_connect(creds: dict[str, str]) -> str:
    """POST the REAL credential values to the mock connect endpoint, return its
    raw response body. Same wire call as the naive arm — the difference is where
    ``creds`` came from (the interrupt channel, not an LLM message)."""
    url = os.environ["BENCH_MOCK_URL"]
    body = json.dumps({k: creds[k] for k in _SECRET_KEYS}).encode()
    return urllib.request.urlopen(
        urllib.request.Request(url, data=body, headers={"content-type": "application/json"})
    ).read().decode()


def _run_isolated(
    llm: Any, variant: str
) -> tuple[Any, dict[str, int], dict[str, Any]]:
    """Hand-architected LangGraph arm: ``interrupt()`` collects the secret
    out-of-band so it NEVER reaches the LLM/proxy.

    Graph: ``plan`` (LLM orchestration, no secret) -> ``connect`` (interrupt() for
    the credentials, POST, DIY outbound scrub) -> ``summarize`` (LLM over the
    scrubbed response). The credentials enter only via ``Command(resume=...)`` at
    the interrupt, exactly analogous to how the driver resumes Colmena's
    secure_suspend — the LLM transcript never carries them, so the proxy leak audit
    stays clean in BOTH collect and echo.
    """
    from langgraph.checkpoint.memory import MemorySaver  # noqa: PLC0415
    from langgraph.graph import END, START, StateGraph  # noqa: PLC0415
    from langgraph.types import Command, interrupt  # noqa: PLC0415

    def plan_node(state: _IsoState) -> dict[str, Any]:
        # The LLM orchestrates the onboarding but is told to pull the credentials
        # from the secure input channel — it never sees or emits them.
        _ask_best_effort(llm, [
            ("system", ss.ONBOARDING_PROMPT),
            ("user", "Begin onboarding. Collect the credentials through the secure "
                     "input channel (do NOT ask me to paste them here), then connect."),
        ])
        return {}

    def connect_node(state: _IsoState) -> dict[str, Any]:
        # NATIVE out-of-band collection: interrupt() suspends the graph; the real
        # credentials arrive via Command(resume=...) into this LOCAL var only.
        creds: dict[str, str] = interrupt(
            {"request": "provide " + ", ".join(_SECRET_KEYS)}
        )
        resp = _post_connect(creds)
        # echo variant: the mock echoes the secret back. DIY OUTBOUND SCRUB — you
        # must strip it by hand before it can reach the summarize node's LLM call.
        # (Colmena re-masks the tool response automatically; here it is on you.)
        for v in ss.secrets().values():
            resp = resp.replace(v, "[REDACTED]")
        return {"status": "connected", "resp": resp}

    def summarize_node(state: _IsoState) -> dict[str, Any]:
        _ask_best_effort(llm, [
            ("system", "Summarize the connection result in one line."),
            ("user", f"The connect endpoint returned: {state.get('resp', '')}"),
        ])
        return {}

    g = StateGraph(_IsoState)
    g.add_node("plan", plan_node)
    g.add_node("connect", connect_node)
    g.add_node("summarize", summarize_node)
    g.add_edge(START, "plan")
    g.add_edge("plan", "connect")
    g.add_edge("connect", "summarize")
    g.add_edge("summarize", END)
    graph = g.compile(checkpointer=MemorySaver())

    config = {"configurable": {"thread_id": "d10-isolated"}}
    result = graph.invoke({}, config=config)
    if "__interrupt__" in result:
        # Resume with the REAL values (the driver's out-of-band "human answer"),
        # exactly as demo_secrets_run resumes Colmena's secure_suspend.
        graph.invoke(Command(resume=ss.secrets()), config=config)

    return (
        "connected",
        {"input": 0, "output": 0, "cached": 0, "tool_calls": 0},
        {"arm": "isolated", "received_path": os.environ.get("BENCH_MOCK_RECORD")},
    )


def run(
    task_def: dict[str, Any], llm: Any, args: RunnerArgs
) -> tuple[Any, dict[str, int], dict[str, Any]]:
    # Steelman arm: hand-architected out-of-band collection via interrupt().
    if os.environ.get("BENCH_LANGGRAPH_ISOLATED") == "1":
        return _run_isolated(llm, args.variant)

    s = ss.secrets()  # {api_key, api_secret, webhook_signing_secret} -> real fake values
    creds = (
        f"api_key={s['api_key']}, api_secret={s['api_secret']}, "
        f"webhook_signing_secret={s['webhook_signing_secret']}"
    )
    # (1) idiomatic collection: the user pastes the credentials into the chat
    #     -> they enter the LLM context -> the proxy audit flags the leak.
    msgs = [
        ("system", ss.ONBOARDING_PROMPT),
        ("assistant", "Please paste your API key, API secret, and webhook signing secret."),
        ("user", f"Here are my credentials: {creds}"),
    ]
    _ = _ask_best_effort(llm, msgs)  # the secrets are now in the prompt -> LEAK

    # (2) connect: POST the 3 REAL values to the mock.
    url = os.environ["BENCH_MOCK_URL"]
    body = json.dumps(
        {k: s[k] for k in ("api_key", "api_secret", "webhook_signing_secret")}
    ).encode()
    resp = urllib.request.urlopen(
        urllib.request.Request(url, data=body, headers={"content-type": "application/json"})
    ).read().decode()

    # (3) final call including the mock response (echo variant: response contains
    #     the secret -> it passes through the LLM here too).
    _ = _ask_best_effort(
        llm,
        [
            ("system", "Summarize the connection result in one line."),
            ("user", f"The connect endpoint returned: {resp}"),
        ],
    )

    return (
        "connected",
        {"input": 0, "output": 0, "cached": 0, "tool_calls": 0},
        {"arm": "naive", "received_path": os.environ.get("BENCH_MOCK_RECORD")},
    )
