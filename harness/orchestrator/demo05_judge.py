"""LLM-judge over SAVED demo05 answers — no agent re-run.

Reads the answers already captured in runs/demo05/n<N>/run_*/report/chart_data.json
and scores each doc-turn answer (0..1) against the source report with an LLM judge
through the proxy. Results are CACHED by a hash of (framework, turn, answer) in
runs/demo05/report/judge_cache.json, so re-running is incremental and cheap — you
can extend turns/passes or add analysis on top without re-judging unchanged answers
and WITHOUT re-running the agents.

Requires the proxy up (it makes judge LLM calls; cheap — only grades saved text):
    PATH=.venv-bench/bin:$PATH BENCH_RUN_ID=judge ./proxy/start_proxy.sh &
    set -a; source .env; set +a
    python harness/orchestrator/demo05_judge.py            # judges doc turns, all passes

Output: runs/demo05/report/judge_n<N>.json + judge_n<N>_summary.csv (per-framework
mean quality score 0..1, mean ± std, n_judged).
"""
from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import os
import statistics
import sys
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = HARNESS_DIR.parent
sys.path.insert(0, str(REPO_ROOT / "runners" / "_bench_common"))
from bench_common import scenario05 as S  # noqa: E402

CACHE_PATH = REPO_ROOT / "runs/demo05/report/judge_cache.json"

JUDGE_SYSTEM = (
    "You are a strict grader. Given a SOURCE REPORT, a QUESTION, and an ANSWER, "
    "score how correct and complete the ANSWER is *with respect to the report* on a "
    "0.0–1.0 scale (1.0 = fully correct and complete; 0.0 = wrong or missing). "
    "Judge only factual fidelity to the report, not style. Reply with ONLY a compact "
    'JSON object: {"score": <float 0..1>, "reason": "<one short sentence>"}.'
)


def _key(fw: str, turn: int, answer: str) -> str:
    h = hashlib.sha1(f"{fw}|{turn}|{answer}".encode()).hexdigest()[:16]
    return f"{fw}:{turn}:{h}"


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text())
    return {}


def _judge_one(client, model: str, run_id: str, question: str, answer: str) -> dict:
    prompt = (
        f"SOURCE REPORT:\n{S.REPORT_TEXT}\n\n"
        f"QUESTION:\n{question}\n\nANSWER:\n{answer}\n\n"
        "Score the ANSWER's factual fidelity to the report."
    )
    resp = client.completion(
        model=f"openai/{model}",
        base_url=os.environ.get("LITELLM_PROXY_BASE_URL", "http://127.0.0.1:4000"),
        api_key=os.environ.get("LITELLM_PROXY_API_KEY")
        or os.environ.get("LITELLM_MASTER_KEY", "sk-x"),
        messages=[{"role": "system", "content": JUDGE_SYSTEM},
                  {"role": "user", "content": prompt}],
        temperature=0.0,
        extra_headers={"x-bench-run-id": run_id},
    )
    text = resp.choices[0].message.content or ""
    # tolerant JSON extraction
    try:
        start = text.index("{"); end = text.rindex("}") + 1
        obj = json.loads(text[start:end])
        score = float(obj.get("score"))
        return {"score": max(0.0, min(1.0, score)), "reason": str(obj.get("reason", ""))[:200]}
    except Exception as e:  # noqa: BLE001
        return {"score": None, "reason": f"parse_error: {type(e).__name__}: {text[:80]}"}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="LLM-judge over saved demo05 answers")
    p.add_argument("--base", type=Path, default=REPO_ROOT / "runs/demo05/n12")
    p.add_argument("--model", default="gemini-2.5-flash")
    p.add_argument("--run-id", default="judge")
    p.add_argument("--turn-types", nargs="*", default=["doc"],
                   help="which turn types to judge (default: doc). Use 'doc follow_up' etc.")
    p.add_argument("--max-passes", type=int, default=0, help="0 = all passes")
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args(argv)

    judged_turns = [i for i, t in enumerate(S.TURNS) if t["type"] in args.turn_types]
    files = sorted(glob.glob(str(args.base / "run_*/report/chart_data.json")))
    if args.max_passes:
        files = files[: args.max_passes]
    if not files:
        print(f"no chart_data under {args.base}")
        return 1

    import litellm  # in .venv-bench
    cache = _load_cache()
    cache_hits = cache_calls = 0
    # framework -> list of scores
    scores: dict[str, list[float]] = {}

    for f in files:
        data = json.loads(Path(f).read_text())
        for r in data:
            fw = r["framework"]
            answers = r.get("answers") or []
            for ti in judged_turns:
                if ti >= len(answers):
                    continue
                ans = str(answers[ti])
                k = _key(fw, ti, ans)
                if k in cache and cache[k].get("score") is not None:
                    res = cache[k]; cache_hits += 1
                else:
                    res = _judge_one(litellm, args.model, args.run_id,
                                     S.TURNS[ti]["message"], ans)
                    cache[k] = res; cache_calls += 1
                    if cache_calls % 10 == 0:
                        CACHE_PATH.write_text(json.dumps(cache, indent=2))
                if res.get("score") is not None:
                    scores.setdefault(fw, []).append(res["score"])

    CACHE_PATH.write_text(json.dumps(cache, indent=2))

    out = {"judged_turns": judged_turns, "n_passes": len(files),
           "cache_hits": cache_hits, "judge_calls": cache_calls, "frameworks": []}
    for fw, sc in scores.items():
        m = statistics.mean(sc) if sc else 0.0
        s = statistics.stdev(sc) if len(sc) > 1 else 0.0
        out["frameworks"].append({"framework": fw, "quality_score_mean": round(m, 4),
                                  "quality_score_std": round(s, 4), "n_judged": len(sc)})
    out["frameworks"].sort(key=lambda r: -r["quality_score_mean"])

    outpath = args.out or (REPO_ROOT / f"runs/demo05/report/judge_n{len(files)}.json")
    outpath.write_text(json.dumps(out, indent=2))
    csvp = outpath.with_name(outpath.stem + "_summary.csv")
    with csvp.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["framework", "quality_score_mean", "quality_score_std", "n_judged"])
        for r in out["frameworks"]:
            w.writerow([r["framework"], r["quality_score_mean"], r["quality_score_std"], r["n_judged"]])

    print(f"judged turns {judged_turns} over {len(files)} passes "
          f"({cache_hits} cached, {cache_calls} new calls) → {outpath.name}, {csvp.name}")
    for r in out["frameworks"]:
        print(f"  {r['framework']:11s} quality {r['quality_score_mean']:.3f} ± "
              f"{r['quality_score_std']:.3f}  (n={r['n_judged']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
