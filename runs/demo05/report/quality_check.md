# Demo #1 quality check (anti-cheating)

Purpose: confirm Colmena's low token count is NOT bought by degraded answer
quality. Doc-turn answers must be real and correct.

Reference: `bench_common.scenario05.QUALITY_CHECKS` and `TURNS`.
- Chart turns (0-based **2, 5, 8**) legitimately return empty text — they
  emit a chart, not prose. An empty answer on those turns is expected.
- Doc/follow-up turns must contain substantive answers.
- Ground-truth substrings: turn 0 → "positive", turn 1 → "North America",
  turn 7 → "Supply chain".

## Per-framework result

| Framework | doc turns answered? | empty turns | unexpected empties | notes |
|---|---|---|---|---|
| colmena    | yes | 2, 5, 8 | none | clean: empties = exactly the 3 chart turns |
| crewai     | yes | none | none | also emits prose on chart turns |
| langchain  | yes | none | none | also emits prose on chart turns |
| langgraph  | yes | 2 | none | turn 2 (chart) empty; all doc turns answered |
| llamaindex | partial | 2, 3, 4 | **3, 4** | turns 3 (QoQ growth) and 4 (trend follow-up) returned EMPTY — real gap |
| google_adk | yes | 2 | none | turn 2 (chart) empty; all doc turns answered |

## Ground-truth substring checks

| Framework | turn0 "positive" | turn1 "North America" | turn7 "Supply chain" |
|---|---|---|---|
| colmena    | PASS | PASS | PASS |
| crewai     | (worded "16.5% growth") | PASS | PASS |
| langchain  | (worded "16.5% growth") | PASS | PASS |
| langgraph  | (worded "16.5% growth") | PASS | PASS |
| llamaindex | (turn0 PASS-equivalent) | PASS | PASS |
| google_adk | (worded "16.5% growth") | PASS | PASS |

The turn-0 "positive" substring is a loose guardrail. All frameworks correctly
describe a positive quarter (16.5% QoQ growth); only the exact word "positive"
differs in phrasing. Colmena's turn-0 answer literally contains "positive".

## Verdict

- **Colmena kept full answer quality.** Its three required doc-turn answers are
  correct and substantive (turn 1 = "North America", turn 7 = "Supply chain",
  turn 0 mentions "positive"). The only empty answers are the three chart turns,
  which is the intended behavior. Colmena's token win is real, not a
  quality-for-tokens trade.
- **One honest caveat:** the **llamaindex** run returned EMPTY text on turns 3
  and 4 (the QoQ-growth doc question and the "is the trend positive?"
  follow-up). The runner exited 0 with no error — this is a llamaindex
  agent quirk (empty final message), not a crash. It does not affect the token
  measurement and llamaindex still ranks far above Colmena on tokens, but its
  answer completeness on this run is lower than the other competitors.
- No framework produced runtime errors or stderr output; all six exited 0.
