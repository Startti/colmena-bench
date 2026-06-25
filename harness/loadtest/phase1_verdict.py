"""Phase-1 go/no-go. Reads runs/demo13/phase1/{colmena,langgraph}.json and decides:
  (A) Is Colmena Serve concurrent? (throughput must rise with C, not flatline at ~1/D)
  (B) Does Colmena win on RAM/session, CPU/request, throughput ceiling, saturation?
Writes VERDICT.md. Exit code 0 = GO, 1 = NO-GO/regression (so CI/scripts can gate).
"""
from __future__ import annotations

import json
import pathlib
import sys

PHASE1 = pathlib.Path("runs/demo13/phase1")


def _load(name):
    return json.loads((PHASE1 / f"{name}.json").read_text())


def _scales_with_concurrency(levels) -> tuple[bool, float]:
    levels = sorted(levels, key=lambda d: d["concurrency"])
    t1 = next(l["throughput_rps"] for l in levels if l["concurrency"] == levels[0]["concurrency"])
    tmax = max(l["throughput_rps"] for l in levels)
    ratio = (tmax / t1) if t1 else 0.0
    # concurrent runtime should at least ~triple throughput from C=1 to its ceiling
    return ratio >= 3.0, ratio


def main() -> None:
    colmena = _load("colmena")
    langgraph = _load("langgraph")
    c_scales, c_ratio = _scales_with_concurrency(colmena["levels"])
    cm, lm = colmena["metrics"], langgraph["metrics"]

    def _min_rss_session(m):
        vals = [v for v in m["rss_per_session_bytes"].values()]
        return min(vals) if vals else float("inf")

    wins = {
        "throughput_ceiling": cm["throughput_ceiling_rps"] >= lm["throughput_ceiling_rps"],
        "rss_per_session": _min_rss_session(cm) <= _min_rss_session(lm),
        "useful_concurrency": cm["useful_concurrency"] >= lm["useful_concurrency"],
    }
    go = c_scales and (sum(wins.values()) >= 2)

    lines = [
        "# demo13 — Phase-1 verdict", "",
        f"**Serve concurrent?** {'YES' if c_scales else 'NO'} "
        f"(throughput C=1->ceiling x{c_ratio:.1f}; need >=3.0)", "",
        "## metrics (colmena vs langgraph)", "",
        f"- throughput ceiling: {cm['throughput_ceiling_rps']:.1f} vs "
        f"{lm['throughput_ceiling_rps']:.1f} rps - colmena {'wins' if wins['throughput_ceiling'] else 'loses'}",
        f"- min RAM/session: {_min_rss_session(cm)/1e6:.1f} vs {_min_rss_session(lm)/1e6:.1f} MB "
        f"- colmena {'wins' if wins['rss_per_session'] else 'loses'}",
        f"- useful concurrency: {cm['useful_concurrency']} vs {lm['useful_concurrency']} "
        f"- colmena {'wins' if wins['useful_concurrency'] else 'loses'}", "",
        f"## Verdict: {'GO' if go else 'NO-GO'}", "",
        "GO => build the other 4 servers (Phase 2). NO-GO => record the null result "
        "honestly and stop, as with demos 11/12.",
    ]
    path = PHASE1 / "VERDICT.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))
    print("\n".join(lines))
    sys.exit(0 if go else 1)


if __name__ == "__main__":
    main()
