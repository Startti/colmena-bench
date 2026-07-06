"""Demo #9 driver — progressive knowledge-loading (skills) across 6 frameworks.

SERIAL sweep over cells = framework x arm x pack_count x seed x question_id.
A single managed proxy is assumed running (see scripts/run_demo09.sh, Task 10);
serial execution is mandatory because Colmena has no x-bench-run-id header, so
its spans land in the proxy fallback session file and are attributed to a cell
by line-count delta — which is only valid when one cell runs at a time.

For each cell it runs one subprocess of that framework's venv with the skills
env, parses the result, scores the numeric answer against the pack's reference
function, and writes ``runs/demo09/summary.{json,csv}``.

Arms:
  naive — stuff EVERY pack's markdown into the system prompt. At pack_count=50
          this exceeds 150k input tokens: the expensive baseline.
  rag   — embed the corpus, retrieve the top-k packs for the question, prompt
          with only those. Adds embedding round-trips.
  colmena — progressive load: the agent navigates the skill tree and loads only
          the leaf it needs. Colmena-only arm.

Corpus materialization:
  Once per (pack_count, seed) actually used: sk.materialize_corpus(dir, M, seed).
  For M==50 we assert corpus_token_estimate(dir) >= 150_000 (the demo premise);
  abort loudly otherwise.

Token measurement (split completion vs embedding by model_alias):
  Header-capable frameworks (all except colmena) tag calls with x-bench-run-id,
  so completion spans land in proxy/spans/run-<run_id>.jsonl. Colmena has no
  header, so its completion spans land in the fallback session file
  run-<PROXY_BENCH_RUN_ID>.jsonl, measured by line-delta around the cell.
  RAG embedding spans use a separate client that may NOT carry the header, so
  they can land in EITHER file; we collect EMBED spans (model_alias==EMBED_MODEL)
  from both and sum them separately.

Cost gate:
  Before the full sweep we estimate naive@50 input tokens and refuse to run
  (without --yes) if the estimate exceeds 20M tokens.

Scoring:
  sk.score_skill_answer(question, str(answer)) -> {"correct": True/False/None}.
  retrieval_hit / skills_used_count are read from the runner's extras.

Support flags:
  --frameworks "a b c"          run a subset (space-separated)
  --arms naive,rag              run a subset of arms (comma-separated)
  --pack-counts 5,20,50         run a subset of pack counts (comma-separated ints)
  --seeds N                     number of seeds (default 3)
  --questions id1,id2           run a subset of QUESTION_BANK ids (comma-sep)
  --merge-baseline <summary.json>  keep other frameworks' rows from a prior run
  --yes                         skip the cost-gate confirmation
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

HARNESS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = HARNESS_DIR.parent
sys.path.insert(0, str(HARNESS_DIR))
sys.path.insert(0, str(HARNESS_DIR / "orchestrator"))
sys.path.insert(0, str(REPO_ROOT / "runners" / "_bench_common"))
sys.path.insert(0, str(HARNESS_DIR / "scoring"))

from orchestrator.full_run import runner_cmd, runner_available, _proxy_key  # noqa: E402
from bench_common import scenario_skills as sk  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FRAMEWORKS = ["colmena", "llamaindex", "langchain", "crewai", "langgraph", "google_adk"]

HEADER_CAPABLE = {"llamaindex", "langchain", "crewai", "langgraph", "google_adk", "mastra"}

ARMS_BY_FW = {
    "colmena": ["colmena"],
    "llamaindex": ["naive", "rag"],
    "langchain": ["naive", "rag"],
    "crewai": ["naive"],
    "langgraph": ["naive"],
    "google_adk": ["naive"],
}

# Floor is the number of core (answerable) packs (6): a smaller corpus would omit
# a core pack and make its questions unanswerable for every arm (see
# scenario_skills.materialize_corpus). Earlier runs used 5 and hit that confound.
PACK_COUNTS = [6, 20, 50]

EMBED_MODEL = os.environ.get("BENCH_EMBED_MODEL", "text-embedding-3-small")

TASK_PATH = REPO_ROOT / "harness" / "tasks" / "09_skills.yaml"  # created in Task 10
CORPUS_ROOT = REPO_ROOT / "runs" / "demo09" / "corpus"

PROXY_BENCH_RUN_ID = os.environ.get("PROXY_BENCH_RUN_ID", "demo09")

PRICING_PATH = HARNESS_DIR / "pricing_table.json"

# Per-cell timeouts. naive@50 sends ~200k+ input tokens; rag adds embedding
# round-trips; colmena navigates the tree with small prompts.
TIMEOUT_NAIVE = 600
TIMEOUT_RAG = 480
TIMEOUT_COLMENA = 360
TIMEOUT_DEFAULT = 360

# Density floor: the 50-pack corpus must exceed this to be the demo's premise.
DENSITY_FLOOR = 150_000

# Cost gate: refuse a full sweep estimated above this without --yes.
COST_GATE_TOKENS = 20_000_000

# ---------------------------------------------------------------------------
# Span / token helpers (mirrored from demo_codeexec_run.py)
# ---------------------------------------------------------------------------


def _line_count(path: "str | Path") -> int:
    """Number of non-empty JSONL lines in `path` (0 if missing)."""
    p = Path(path)
    if not p.exists():
        return 0
    return sum(1 for line in p.read_text().splitlines() if line.strip())


def _load_spans_from_offset(path: "str | Path", offset: int) -> list[dict]:
    """Parse JSONL span dicts AFTER `offset` lines (empty list if missing)."""
    p = Path(path)
    if not p.exists():
        return []
    lines = [line for line in p.read_text().splitlines() if line.strip()]
    spans: list[dict] = []
    for line in lines[offset:]:
        try:
            spans.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return spans


def _sum_tokens(spans: list[dict]) -> tuple[int, int]:
    """Return (tokens_in, tokens_out) summed over all spans."""
    tin = sum(s.get("tokens_input", 0) for s in spans)
    tout = sum(s.get("tokens_output", 0) for s in spans)
    return tin, tout


# ---------------------------------------------------------------------------
# Question bank lookup
# ---------------------------------------------------------------------------


def _question_by_id(qid: str) -> "sk.Question | None":
    for q in sk.QUESTION_BANK:
        if q.id == qid:
            return q
    return None


# ---------------------------------------------------------------------------
# Corpus materialization (once per (pack_count, seed))
# ---------------------------------------------------------------------------


def _materialize(pack_count: int, seed: int) -> Path:
    """Materialize (or reuse) the corpus for one (pack_count, seed). For M==50
    assert the density floor and abort loudly otherwise."""
    corpus_dir = CORPUS_ROOT / f"m{pack_count}_s{seed}"
    sk.materialize_corpus(str(corpus_dir), pack_count, seed)
    if pack_count == 50:
        est = sk.corpus_token_estimate(str(corpus_dir))
        if est < DENSITY_FLOOR:
            raise SystemExit(
                f"[demo09] FATAL: m50/s{seed} corpus token estimate {est} < "
                f"density floor {DENSITY_FLOOR}. The 50-pack corpus MUST be dense "
                f"(>=150k tokens) — that density is the whole premise of the demo. "
                f"Fix scenario_skills._DISTRACTOR_ROWS / distractor sizing."
            )
        print(f"[demo09] m{pack_count}/s{seed} corpus ~{est} tokens (>= {DENSITY_FLOOR} ok)")
    return corpus_dir


# ---------------------------------------------------------------------------
# Cost gate
# ---------------------------------------------------------------------------


def _gemini_input_price() -> "float | None":
    """gemini-2.5-flash input USD per 1M tokens, or None if unavailable."""
    try:
        pricing = json.loads(PRICING_PATH.read_text())
        return pricing["models"]["gemini-2.5-flash"]["input_per_1m"]
    except Exception:  # noqa: BLE001
        return None


def _cost_gate(
    fw_list: list[str],
    arms: list[str],
    pack_counts: list[int],
    questions: list[str],
    n_seeds: int,
    yes: bool,
) -> None:
    """Estimate naive@50 input tokens and abort (without --yes) above threshold.

    naive@50 input tokens ~= corpus_token_estimate(m50 corpus) * (#naive cells at M=50),
    where #naive cells at M=50 = (#naive frameworks selected) * (#questions) * (#seeds).
    """
    if 50 not in pack_counts or "naive" not in arms:
        return  # nothing at naive@50 to gate on

    # Materialize the m50/s0 corpus to get a real token estimate (cheap, reused later).
    m50_dir = _materialize(50, 0)
    per_naive_in = sk.corpus_token_estimate(str(m50_dir))

    naive_fws = [
        fw for fw in fw_list
        if "naive" in [a for a in ARMS_BY_FW.get(fw, []) if a in arms]
    ]
    n_naive_cells = len(naive_fws) * len(questions) * n_seeds
    est_tokens = per_naive_in * n_naive_cells

    price = _gemini_input_price()
    usd_note = ""
    if price is not None:
        usd = est_tokens / 1_000_000 * price
        usd_note = f"  (~${usd:,.2f} input @ ${price}/1M gemini-2.5-flash)"

    print(
        f"[demo09] cost gate: naive@50 estimate ~{est_tokens:,} input tokens "
        f"({per_naive_in:,} tok/cell x {n_naive_cells} naive cells){usd_note}"
    )

    if est_tokens > COST_GATE_TOKENS and not yes:
        raise SystemExit(
            f"[demo09] ABORT: estimated naive@50 input is {est_tokens:,} tokens, "
            f"above the {COST_GATE_TOKENS:,}-token cost gate. This is a large/expensive "
            f"run. Re-run with --yes to proceed, or narrow --frameworks / --pack-counts / "
            f"--questions / --seeds."
        )


# ---------------------------------------------------------------------------
# Subprocess env + invocation
# ---------------------------------------------------------------------------


def _env_for(fw: str, run_id: str, proxy_base_url: str,
             corpus_dir: Path, arm: str, qid: str) -> dict[str, str]:
    """Build the subprocess environment for one skills cell."""
    env = os.environ.copy()
    env.update({
        "BENCH_RUN_ID": run_id,
        "BENCH_SKILLS_DIR": str(corpus_dir),
        "BENCH_SKILLS_ARM": arm,
        "BENCH_QUESTION_ID": qid,
        "BENCH_EMBED_MODEL": EMBED_MODEL,
        "LITELLM_PROXY_BASE_URL": proxy_base_url,
        "LITELLM_PROXY_API_KEY": _proxy_key(),
        "PYTHONPATH": (
            f"{REPO_ROOT / 'runners' / fw}:"
            f"{REPO_ROOT / 'runners' / '_bench_common'}"
        ),
    })
    if fw == "colmena":
        env.setdefault("COLMENA_CHEAP_MODEL_OPENAI", "gemini-2.5-flash")
        # DATABASE_URL must be present BEFORE the colmena engine builds.
        if not env.get("DATABASE_URL") and env.get("COLMENA_DATABASE_URL"):
            env["DATABASE_URL"] = env["COLMENA_DATABASE_URL"]
        env.setdefault("SECURE_VALUES_KEY", "0" * 64)
        env.setdefault("COLMENA_LOCAL_STORAGE_DIR", "/tmp/colmena-bench-storage")
    return env


def _invoke(fw: str, run_id: str, model_alias: str, proxy_base_url: str,
            corpus_dir: Path, arm: str, qid: str,
            out_path: Path, timeout: int) -> subprocess.CompletedProcess:
    """Invoke the framework runner for one skills cell. The task yaml declares a
    "default" variant; the handler ignores --variant and reads the BENCH_SKILLS_*
    env, so we always pass --variant default."""
    cmd = runner_cmd(fw) + [
        "--task", str(TASK_PATH),
        "--variant", "default",
        "--run-id", run_id,
        "--model-alias", model_alias,
        "--proxy-base-url", proxy_base_url,
        "--output", str(out_path),
        "--timeout-seconds", str(timeout),
    ]
    env = _env_for(fw, run_id, proxy_base_url, corpus_dir, arm, qid)
    return subprocess.run(
        cmd, env=env, capture_output=True, text=True,
        timeout=timeout + 120,
    )


# ---------------------------------------------------------------------------
# Per-cell runner
# ---------------------------------------------------------------------------


def _timeout_for(fw: str, arm: str) -> int:
    if arm == "rag":
        return TIMEOUT_RAG
    if arm == "naive":
        return TIMEOUT_NAIVE
    if fw == "colmena":
        return TIMEOUT_COLMENA
    return TIMEOUT_DEFAULT


def _run_cell(
    fw: str,
    arm: str,
    pack_count: int,
    seed: int,
    qid: str,
    corpus_dir: Path,
    model_alias: str,
    proxy_base_url: str,
    out_dir: Path,
    spans_dir: Path,
    session_file: Path,
) -> dict[str, Any]:
    """Run one (fw, arm, pack_count, seed, qid) cell; return a summary row dict."""

    question = _question_by_id(qid)
    base_row: dict[str, Any] = {
        "framework": fw,
        "arm": arm,
        "pack_count": pack_count,
        "seed": seed,
        "question_id": qid,
        "pack": question.pack if question else None,
    }

    if not runner_available(fw):
        return {**base_row, "skipped": True, "skip_reason": "no venv"}
    if question is None:
        return {**base_row, "skipped": True, "skip_reason": f"unknown question id {qid}"}

    run_id = f"d9-{fw}-{arm}-m{pack_count}-s{seed}-{qid}"
    out_path = out_dir / f"{run_id}.json"
    timeout = _timeout_for(fw, arm)

    # Snapshot the fallback session file (colmena + RAG-embed may land here).
    pre_session = _line_count(session_file)

    # Clear this cell's per-run span file BEFORE invoking. The proxy APPENDS to
    # run-<run_id>.jsonl, and run_id is deterministic per cell, so a re-run would
    # otherwise sum old+new spans and inflate token counts. Safe no-op for colmena
    # (it has no x-bench-run-id header and writes to the fallback session file).
    run_span_file = spans_dir / f"run-{run_id}.jsonl"
    try:
        run_span_file.unlink()
    except FileNotFoundError:
        pass

    try:
        proc = _invoke(fw, run_id, model_alias, proxy_base_url,
                       corpus_dir, arm, qid, out_path, timeout)
        returncode = proc.returncode
        stderr = proc.stderr
    except subprocess.TimeoutExpired as e:
        returncode = -1
        stderr = f"TimeoutExpired: {e}"

    # Parse output JSON.
    out_data: dict[str, Any] = {}
    if out_path.exists():
        try:
            out_data = json.loads(out_path.read_text())
        except json.JSONDecodeError:
            pass

    extras = out_data.get("extras") or {}
    runner_error = out_data.get("error")
    answer = out_data.get("answer")

    if returncode != 0 and stderr:
        out_path.with_suffix(".stderr").write_text(stderr)

    # Handler-level skip (e.g. crewai without Docker, arm unsupported).
    if extras.get("skipped"):
        return {**base_row, "skipped": True,
                "skip_reason": extras.get("reason", "handler skipped")}

    # Collect spans for token accounting (do this even on error so we can still
    # report the input cost of a failed naive@50 cell).
    run_spans = _load_spans_from_offset(spans_dir / f"run-{run_id}.jsonl", 0)
    session_new = _load_spans_from_offset(session_file, pre_session)

    embed_spans = [
        s for s in (run_spans + session_new)
        if s.get("model_alias") == EMBED_MODEL
    ]
    if fw == "colmena":
        completion_spans = [s for s in session_new if s.get("model_alias") != EMBED_MODEL]
    else:
        completion_spans = [s for s in run_spans if s.get("model_alias") != EMBED_MODEL]

    llm_tokens_in, llm_tokens_out = _sum_tokens(completion_spans)
    embed_tokens = sum(s.get("tokens_input", 0) for s in embed_spans)

    # Embed-token fallback (Decision B): RAG embeddings bypass the proxy
    # (direct-to-OpenAI, since the proxy /embeddings route needs a DB), so the
    # span-based count is 0. Estimate from the handler's reported embed_chars at
    # ~4 chars/token. The span-based path runs first, so a future proxy fix that
    # routes embeddings would yield real numbers and win.
    embed_estimated = False
    if arm == "rag" and embed_tokens == 0:
        embed_tokens = int(extras.get("embed_chars", 0)) // 4
        embed_estimated = True

    # Hard error?
    if returncode != 0 or runner_error:
        return {**base_row, "skipped": False,
                "correct": None,
                "llm_tokens_in": llm_tokens_in,
                "llm_tokens_out": llm_tokens_out,
                "embed_tokens": embed_tokens,
                "embed_estimated": embed_estimated,
                "retrieval_hit": extras.get("retrieval_hit"),
                "skills_used_count": extras.get("skills_used_count", 0),
                "error": runner_error or f"exit {returncode}",
                "stderr_tail": stderr[-600:] if stderr else None}

    # Score the numeric answer.
    score = sk.score_skill_answer(question, str(answer))

    return {
        **base_row,
        "skipped": False,
        "error": None,
        "correct": score["correct"],
        "llm_tokens_in": llm_tokens_in,
        "llm_tokens_out": llm_tokens_out,
        "embed_tokens": embed_tokens,
        "embed_estimated": embed_estimated,
        "retrieval_hit": extras.get("retrieval_hit"),
        "skills_used_count": extras.get("skills_used_count", 0),
    }


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

SUMMARY_COLS = [
    "framework", "arm", "pack_count", "seed", "question_id", "pack",
    "correct",
    "llm_tokens_in", "llm_tokens_out", "embed_tokens", "embed_estimated",
    "retrieval_hit",
    "skills_used_count",
    "error", "skipped",
]


def _write_outputs(rows: list[dict[str, Any]], runs_dir: Path) -> tuple[Path, Path]:
    runs_dir.mkdir(parents=True, exist_ok=True)
    json_path = runs_dir / "summary.json"
    csv_path = runs_dir / "summary.csv"
    json_path.write_text(json.dumps(rows, indent=2, default=str))

    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SUMMARY_COLS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            out = {}
            for c in SUMMARY_COLS:
                v = r.get(c)
                out[c] = "" if v is None else v
            w.writerow(out)
    return json_path, csv_path


def _print_row(row: dict[str, Any]) -> None:
    tag = (f"{row.get('framework','?')} {row.get('arm','?')}/"
           f"m{row.get('pack_count','?')}/s{row.get('seed','?')}/"
           f"{row.get('question_id','?')}")
    if row.get("skipped"):
        print(f"    [{tag}] SKIPPED ({row.get('skip_reason','')})")
        return
    if row.get("error"):
        print(f"    [{tag}] ERROR: {row['error']}  "
              f"tok_in={row.get('llm_tokens_in',0)} embed={row.get('embed_tokens',0)}")
        return
    correct = row.get("correct")
    c = "OK" if correct is True else ("X" if correct is False else "-")
    parts = [f"correct={c}",
             f"llm={row.get('llm_tokens_in',0)}/{row.get('llm_tokens_out',0)}",
             f"embed={row.get('embed_tokens',0)}"]
    if row.get("retrieval_hit") is not None:
        parts.append(f"hit={row['retrieval_hit']}")
    if row.get("skills_used_count"):
        parts.append(f"skills={row['skills_used_count']}")
    print(f"    [{tag}] {' '.join(parts)}")


def _print_summary(rows: list[dict[str, Any]]) -> None:
    print("\n=== Demo #9 — skills summary ===")
    hdr = (f"{'framework':<12} {'arm':<8} {'M':>3} {'s':>2} {'qid':<18} "
           f"{'corr':>5} {'llm_in':>8} {'llm_out':>7} {'embed':>8}")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        if r.get("skipped"):
            print(f"{r.get('framework',''):<12} {r.get('arm',''):<8} "
                  f"{str(r.get('pack_count','')):>3} {str(r.get('seed','')):>2} "
                  f"{str(r.get('question_id','')):<18}  SKIPPED")
            continue
        correct = r.get("correct")
        c = "OK" if correct is True else ("X" if correct is False else "-")
        if r.get("error"):
            c = "ERR"
        print(f"{r.get('framework',''):<12} {r.get('arm',''):<8} "
              f"{str(r.get('pack_count','')):>3} {str(r.get('seed','')):>2} "
              f"{str(r.get('question_id','')):<18} {c:>5} "
              f"{str(r.get('llm_tokens_in',0)):>8} {str(r.get('llm_tokens_out',0)):>7} "
              f"{str(r.get('embed_tokens',0)):>8}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Demo #9 — skills (progressive knowledge-loading) driver")
    p.add_argument("--model-alias", default="gemini-2.5-flash")
    p.add_argument("--proxy-base-url", default="http://127.0.0.1:4000")
    p.add_argument("--frameworks", default=None,
                   help="space-separated framework names (default: all 6)")
    p.add_argument("--arms", default=None,
                   help="comma-separated arms: naive,rag,colmena (default: all per framework)")
    p.add_argument("--pack-counts", default=None,
                   help="comma-separated pack counts, e.g. 5,20,50 (default: 5,20,50)")
    p.add_argument("--seeds", type=int, default=3,
                   help="number of seeds, 0..N-1 (default: 3)")
    p.add_argument("--questions", default=None,
                   help="comma-separated QUESTION_BANK ids (default: all)")
    p.add_argument("--out-dir", type=Path,
                   default=REPO_ROOT / "runs" / "demo09" / "raw")
    p.add_argument("--spans-dir", type=Path,
                   default=REPO_ROOT / "proxy" / "spans")
    p.add_argument("--runs-dir", type=Path,
                   default=REPO_ROOT / "runs" / "demo09")
    p.add_argument("--merge-baseline", type=Path, default=None,
                   help="path to an existing summary.json; keep other frameworks' "
                        "rows and merge with fresh runs")
    p.add_argument("--yes", action="store_true",
                   help="skip the cost-gate confirmation for large runs")
    args = p.parse_args(argv)

    # Parse subset filters.
    fw_list = args.frameworks.split() if args.frameworks else list(FRAMEWORKS)
    arms = ([a.strip() for a in args.arms.split(",")] if args.arms
            else ["naive", "rag", "colmena"])
    pack_counts = ([int(x.strip()) for x in args.pack_counts.split(",")]
                   if args.pack_counts else list(PACK_COUNTS))
    all_qids = [q.id for q in sk.QUESTION_BANK]
    questions = ([q.strip() for q in args.questions.split(",")]
                 if args.questions else all_qids)
    # Validate question ids.
    unknown = [q for q in questions if q not in all_qids]
    if unknown:
        raise SystemExit(f"[demo09] unknown question id(s): {unknown}. "
                         f"Known: {all_qids}")
    seeds = list(range(args.seeds))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.spans_dir.mkdir(parents=True, exist_ok=True)

    session_file = args.spans_dir / f"run-{PROXY_BENCH_RUN_ID}.jsonl"
    print(f"[demo09] colmena/fallback session file: {session_file}")
    print(f"[demo09] frameworks: {fw_list}")
    print(f"[demo09] arms (filter): {arms}")
    print(f"[demo09] pack_counts: {pack_counts}")
    print(f"[demo09] seeds: {seeds}")
    print(f"[demo09] questions: {len(questions)} of {len(all_qids)}")
    print(f"[demo09] embed model: {EMBED_MODEL}")

    # Cost gate (before the full sweep). Materializes m50/s0 internally.
    _cost_gate(fw_list, arms, pack_counts, questions, len(seeds), args.yes)

    # Materialize all corpora up front (idempotent; reused across cells).
    corpus_dirs: dict[tuple[int, int], Path] = {}
    for M in pack_counts:
        for s in seeds:
            corpus_dirs[(M, s)] = _materialize(M, s)

    rows: list[dict[str, Any]] = []

    # SERIAL sweep: framework x arm x pack_count x seed x question.
    for fw in fw_list:
        fw_arms = [a for a in ARMS_BY_FW.get(fw, []) if a in arms]
        for arm in fw_arms:
            for M in pack_counts:
                for s in seeds:
                    corpus_dir = corpus_dirs[(M, s)]
                    for qid in questions:
                        print(f"==> {fw} {arm}/m{M}/s{s}/{qid}")
                        row = _run_cell(
                            fw=fw, arm=arm, pack_count=M, seed=s, qid=qid,
                            corpus_dir=corpus_dir,
                            model_alias=args.model_alias,
                            proxy_base_url=args.proxy_base_url,
                            out_dir=args.out_dir, spans_dir=args.spans_dir,
                            session_file=session_file,
                        )
                        rows.append(row)
                        _print_row(row)

    # Merge with baseline if requested (keep rows for frameworks NOT run now).
    if args.merge_baseline and args.merge_baseline.exists():
        ran_fws = set(fw_list)
        baseline = json.loads(args.merge_baseline.read_text())
        kept = [r for r in baseline if r.get("framework") not in ran_fws]
        print(f"[merge] kept {len(kept)} baseline rows (frameworks not in this run); "
              f"added {len(rows)} fresh rows")
        rows = kept + rows

    json_path, csv_path = _write_outputs(rows, args.runs_dir)
    _print_summary(rows)
    print(f"\nwrote {json_path}")
    print(f"wrote {csv_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
