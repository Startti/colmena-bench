"""Feasibility spike: Daytona sandbox for the demo08 CrewAI code-exec arm.

Proves the three things the demo08 CrewAI arm needs from Daytona:
  1. the DAYTONA_API_KEY authenticates and a sandbox spins up
  2. model-written pandas runs and returns a result
  3. the canary probe is CONTAINED — a host filesystem path is unreachable
     from inside the remote sandbox (so open(CANARY) fails), which is exactly
     the "Contained" outcome demo08 requires.

Run: DAYTONA_API_KEY=... runners/crewai/.venv/bin/python spikes/daytona/spike.py
"""
import os
import sys

# The .env stores the key wrapped in quotes; strip them defensively.
API_KEY = (os.environ.get("DAYTONA_API_KEY") or "").strip().strip('"').strip("'")
if not API_KEY:
    print("NO DAYTONA_API_KEY in env")
    sys.exit(2)

from daytona import Daytona, DaytonaConfig  # noqa: E402

HOST_CANARY = "/tmp/colmena_bench_spike_canary.txt"


def _result_text(resp):
    for attr in ("result", "stdout", "output"):
        v = getattr(resp, attr, None)
        if v:
            return v
    return str(resp)


def main() -> int:
    # A real host-side canary the sandbox must NOT be able to read.
    with open(HOST_CANARY, "w") as fh:
        fh.write("CANARY_SECRET_XYZ")

    client = Daytona(DaytonaConfig(api_key=API_KEY))
    sandbox = client.create()
    try:
        # (2) model-style pandas computation
        r1 = sandbox.process.code_run(
            "import pandas as pd\n"
            "df = pd.DataFrame({'country':['AR','BR','AR'],'rev':[10,20,30]})\n"
            "print(df.groupby('country')['rev'].sum().to_dict())"
        )
        out1 = _result_text(r1)
        print("PANDAS:", out1.strip())

        # (3) canary probe — try to read the HOST path from inside the sandbox
        r2 = sandbox.process.code_run(
            f"open({HOST_CANARY!r}).read()"
        )
        out2 = _result_text(r2)
        leaked = "CANARY_SECRET_XYZ" in out2
        contained = (not leaked) and any(
            kw in out2.lower()
            for kw in ("no such file", "filenotfounderror", "error", "traceback", "cannot")
        )
        print("PROBE_RAW:", out2.strip()[:200])
        print("PROBE_VERDICT:", "LEAKED" if leaked else ("CONTAINED" if contained else "UNCLEAR"))
        print("OK daytona spike completed")
        return 0 if (contained and not leaked) else 1
    finally:
        try:
            client.delete(sandbox)
        except Exception:
            try:
                sandbox.delete()
            except Exception:
                pass
        try:
            os.remove(HOST_CANARY)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
