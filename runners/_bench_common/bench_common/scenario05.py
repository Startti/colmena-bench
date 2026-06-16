"""Shared, deterministic assets for Hero Demo #1 (context-tax asymptote).

Every runner imports these so the document, the 10-turn script, and the chart
tool's output are provably identical across all 6 frameworks. See
docs/superpowers/specs/2026-06-16-context-scrubbing-demo-design.md.
"""
from __future__ import annotations

import base64

REPORT_DOC_ID = "q3_report"
REPORT_FILENAME = "Q3_2026_report.md"

# A fixed synthetic quarterly report. Long enough (~12-15 "pages") that carrying
# it in history every turn dominates the token asymptote. Content is invented
# and internally consistent so doc questions have real answers.
_REGIONS = [
    ("North America", 4200, 3800, 11),
    ("Europe", 3100, 2900, 7),
    ("Latin America", 1800, 1300, 38),
    ("Asia Pacific", 2600, 2100, 24),
    ("Middle East & Africa", 900, 720, 25),
]
_MONTHS = [
    ("July", 3990), ("August", 4070), ("September", 4150),
]
_RISKS = [
    ("Supply chain concentration", "High",
     "62% of components sourced from a single region; a disruption would stall fulfilment."),
    ("FX exposure in Latin America", "Medium",
     "Revenue booked in volatile local currencies without full hedging."),
    ("Customer concentration", "Medium",
     "Top 3 accounts represent 28% of ARR; churn of any one materially dents revenue."),
    ("Talent attrition in engineering", "Low",
     "Voluntary attrition rose to 14% annualised, above the 10% target."),
]


def _build_report() -> str:
    lines: list[str] = []
    lines.append("# Q3 2026 Business Review — Acme Analytics, Inc.\n")
    lines.append(
        "This confidential quarterly review summarises revenue performance by "
        "region, the monthly demand trend, the principal risks facing the "
        "business, and management's outlook for Q4 2026. All figures are in "
        "thousands of USD unless stated otherwise.\n"
    )
    lines.append("## 1. Executive summary\n")
    total_rev = sum(r[1] for r in _REGIONS)
    total_prev = sum(r[2] for r in _REGIONS)
    growth = (total_rev - total_prev) / total_prev * 100
    lines.append(
        f"Total revenue for Q3 2026 was ${total_rev:,}k, up from ${total_prev:,}k "
        f"in Q2 2026 — a quarter-over-quarter growth rate of {growth:.1f}%. Growth "
        "was led by Latin America and Asia Pacific, while North America remained "
        "the largest absolute contributor. Management views the trend as positive "
        "but flags supply-chain concentration as the dominant risk.\n"
    )
    lines.append("## 2. Revenue by region\n")
    lines.append("| Region | Q3 2026 | Q2 2026 | QoQ growth % |")
    lines.append("|---|--:|--:|--:|")
    for name, cur, prev, g in _REGIONS:
        lines.append(f"| {name} | {cur} | {prev} | {g}% |")
    lines.append("")
    for name, cur, prev, g in _REGIONS:
        lines.append(
            f"### {name}\n{name} posted ${cur:,}k in Q3 2026 versus ${prev:,}k in "
            f"Q2 2026, a growth of {g}%. " + (
                "This was the fastest-growing region in the period, driven by new "
                "logo acquisition and expansion within existing accounts. "
                if g >= 24 else
                "Performance was steady, reflecting a mature market with stable "
                "renewal rates and modest expansion. "
            ) + "Regional management expects this trajectory to continue into Q4, "
            "subject to the macro conditions described in Section 5.\n"
        )
    lines.append("## 3. Monthly demand trend\n")
    lines.append("| Month | Bookings |")
    lines.append("|---|--:|")
    for mname, val in _MONTHS:
        lines.append(f"| {mname} | {val} |")
    lines.append("")
    lines.append(
        "Monthly bookings rose every month of the quarter, from "
        f"{_MONTHS[0][1]} in {_MONTHS[0][0]} to {_MONTHS[-1][1]} in "
        f"{_MONTHS[-1][0]}, an unbroken upward trend that management reads as "
        "evidence of strengthening demand rather than seasonal noise. "
        "The sequential acceleration across all three months reinforces "
        "confidence in the Q4 revenue plan.\n"
    )
    lines.append("## 4. Principal risks\n")
    for i, (title, sev, detail) in enumerate(_RISKS, 1):
        lines.append(f"### 4.{i} {title} (severity: {sev})\n{detail}\n")
    lines.append("## 5. Outlook and macro context\n")
    # Pad with substantive, varied prose so the doc reaches ~12-15 pages without
    # being filler the model can't reason about.
    for name, cur, prev, g in _REGIONS:
        lines.append(
            f"For {name}, the Q4 plan assumes continued {g}% momentum, partially "
            "offset by tougher comparables. The pipeline coverage ratio stands at "
            "3.1x, above the 3.0x threshold management considers healthy. Sales "
            "cycles lengthened slightly versus Q2, which the revenue operations "
            "team attributes to increased procurement scrutiny among enterprise "
            "buyers. Mitigations include earlier multi-threading and tighter "
            "qualification at the top of funnel.\n"
        )
    lines.append("## 6. Product line breakdown\n")
    lines.append(
        "Acme Analytics offers three core product lines: Platform (the core SaaS "
        "analytics suite), Connectors (pre-built data integrations), and Services "
        "(implementation and training). In Q3 2026, Platform contributed 68% of "
        "total revenue ($8,568k), Connectors contributed 19% ($2,394k), and "
        "Services contributed 13% ($1,638k). Platform growth of 18% QoQ was the "
        "primary driver of aggregate performance. Connectors revenue was flat due "
        "to a pricing renegotiation with a large partner that resolved in late "
        "August; the impact is expected to be transient. Services revenue grew 9% "
        "QoQ reflecting higher implementation volumes tied to new Platform logos.\n"
    )
    lines.append("| Product Line | Q3 Revenue | Q2 Revenue | QoQ % | Notes |")
    lines.append("|---|--:|--:|--:|---|")
    lines.append("| Platform | 8,568 | 7,261 | +18% | New logo and expansion |")
    lines.append("| Connectors | 2,394 | 2,381 | +1% | Partner renegotiation |")
    lines.append("| Services | 1,638 | 1,503 | +9% | Higher impl. volumes |")
    lines.append("")
    lines.append("## 7. Customer cohort analysis\n")
    lines.append(
        "The company ended Q3 2026 with 412 paying accounts, up from 387 at the "
        "end of Q2 2026 — net new logo count of 25. Gross logo churn was 3 "
        "accounts (0.8%), all in the SMB segment, compared with 5 churned accounts "
        "in Q2 2026. Net revenue retention (NRR) stood at 118%, reflecting strong "
        "expansion activity. The median contract value increased from $28k to $31k "
        "ARR, driven by upsell of the Platform's advanced analytics module.\n"
    )
    lines.append(
        "The top 10 accounts by ARR contributed 41% of total revenue in Q3 2026. "
        "The single largest account, a global logistics firm, expanded its contract "
        "by 35% to $520k ARR during the quarter. Account management logged 148 "
        "expansion calls in Q3 2026, up from 112 in Q2 2026, reflecting a "
        "deliberate shift toward land-and-expand motion.\n"
    )
    lines.append("| Segment | Accounts | Avg ARR ($k) | NRR |")
    lines.append("|---|--:|--:|--:|")
    lines.append("| Enterprise (>$100k ARR) | 58 | 210 | 126% |")
    lines.append("| Mid-market ($20k–$100k ARR) | 189 | 42 | 119% |")
    lines.append("| SMB (<$20k ARR) | 165 | 11 | 103% |")
    lines.append("")
    lines.append("## 8. Headcount and operating expenses\n")
    lines.append(
        "Total headcount at the close of Q3 2026 was 284, up from 271 at the close "
        "of Q2 2026. Engineering accounted for 112 employees (39%), Go-to-Market "
        "for 98 (35%), and General & Administrative for 74 (26%). Voluntary "
        "attrition in engineering was 14% annualised — above the 10% target set at "
        "the start of the fiscal year. People operations has launched a retention "
        "programme including equity refresh grants and a technical career ladder "
        "revision; early indicators suggest voluntary quit rates in July and August "
        "were lower than the Q3 average.\n"
    )
    lines.append(
        "Operating expenditure in Q3 2026 was $9,840k against $9,100k in Q2 2026, "
        "an 8% increase. The largest line items were employee costs ($6,200k), "
        "cloud infrastructure ($1,450k), and external contractors ($890k). "
        "Infrastructure costs grew 12% QoQ due to a data-centre migration that "
        "completed in July; the migration is expected to reduce per-unit costs by "
        "approximately 8% from Q4 2026 onwards once reserved-instance pricing "
        "takes effect.\n"
    )
    lines.append("## 9. Competitive landscape\n")
    lines.append(
        "The analytics SaaS market remained intensely competitive in Q3 2026. "
        "Acme Analytics's primary competitors — Prism Data, VelocityBI, and the "
        "analytics modules of the major cloud hyperscalers — continued to invest "
        "heavily in product development. Acme's differentiated strengths in the "
        "quarter were: (1) a data-residency architecture enabling on-premise "
        "deployment in regulated industries, which drove two enterprise wins in the "
        "healthcare vertical; (2) the breadth of the Connectors library, now "
        "exceeding 340 pre-built integrations; and (3) a mobile-first reporting "
        "experience that resonated with logistics and field-service buyers.\n"
    )
    lines.append(
        "Competitive win/loss data for Q3 2026 (from 74 tracked competitive deals): "
        "Acme won 47 (64%), lost 19 (26%), and 8 deals remain in evaluation. Win "
        "rate improved from 59% in Q2 2026. The most common loss reason cited by "
        "prospects was pricing (38% of losses), followed by missing features in "
        "predictive analytics (29%) and incumbent vendor inertia (21%).\n"
    )
    lines.append("## 10. Go-to-market metrics and Q4 targets\n")
    lines.append(
        "The sales development team generated 1,240 qualified opportunities in "
        "Q3 2026, up 17% from 1,059 in Q2 2026. The average sales cycle for "
        "enterprise deals was 74 days, compared with 68 days in Q2 2026. "
        "Management attributes the elongation to heightened procurement scrutiny "
        "and increased committee sizes among enterprise buyers. Mid-market cycles "
        "averaged 31 days, broadly stable quarter-over-quarter.\n"
    )
    lines.append(
        "For Q4 2026, the revenue plan calls for total bookings of $14,200k, a "
        "12.7% sequential increase. By region, the plan is: North America $4,700k "
        "(+12% QoQ), Europe $3,400k (+10% QoQ), Latin America $2,000k (+11% QoQ), "
        "Asia Pacific $3,000k (+15% QoQ), and Middle East & Africa $1,100k (+22% "
        "QoQ). Key assumptions are: (1) no macro deterioration in the eurozone; "
        "(2) resolution of the Latin America FX hedging programme by October; and "
        "(3) successful on-boarding of 18 pipeline enterprise accounts currently "
        "at contract stage.\n"
    )
    lines.append(
        "Marketing generated 3,820 marketing-qualified leads (MQLs) in Q3 2026 "
        "versus 3,210 in Q2 2026 (+19%). The MQL-to-SQL conversion rate improved "
        "from 33% to 36%, reflecting tighter targeting criteria introduced in July. "
        "The cost per MQL declined from $142 to $128. Paid search remained the "
        "largest single channel (42% of MQLs), followed by content/organic (28%), "
        "field events (18%), and partner referrals (12%). The Q4 marketing budget "
        "allocates an additional $200k to field events in Asia Pacific and "
        "$150k to a content localisation programme for Latin America.\n"
    )
    lines.append("## 11. Methodology and definitions\n")
    lines.append(
        "Revenue is recognised on delivery in accordance with the company's "
        "standard policy. 'Bookings' denotes the total contract value signed in "
        "the month. 'QoQ growth' compares Q3 2026 to Q2 2026. Regional figures "
        "are allocated by customer billing address. 'ARR' (Annual Recurring "
        "Revenue) is calculated as monthly recurring revenue multiplied by 12. "
        "'NRR' (Net Revenue Retention) measures revenue from the existing customer "
        "cohort at the start of the period relative to revenue from that same "
        "cohort at the end of the period, including expansions and contractions but "
        "excluding new logos. This report is unaudited and intended for internal "
        "management review only. Recipients should not distribute this document "
        "outside the company without prior written approval from the CFO.\n"
    )
    return "\n".join(lines)


REPORT_TEXT = _build_report()

# Ground-truth facts derived from the report, for the light quality guardrail.
_TOTAL_REV = sum(r[1] for r in _REGIONS)
QUALITY_CHECKS = {
    # turn index (0-based) -> list of substrings that a correct answer should contain
    0: ["positive"],                      # key findings mention positive trend
    1: ["North America"],                 # highest revenue region
    7: ["Supply chain"],                  # top risk
}

TURNS = [
    {"type": "doc", "message": "Summarize the key findings of the attached report."},
    {"type": "doc", "message": "Which region had the highest revenue in Q3 2026?"},
    {"type": "chart", "message": "Generate a bar chart of revenue by region."},
    {"type": "doc", "message": "What was the quarter-over-quarter revenue growth rate?"},
    {"type": "follow_up", "message": "Based on that, is the overall trend positive?"},
    {"type": "chart", "message": "Generate a line chart of the monthly bookings trend."},
    {"type": "follow_up", "message": "In one sentence, what do the two charts together show?"},
    {"type": "doc", "message": "What were the top 3 risks listed in the report?"},
    {"type": "chart", "message": "Generate a chart of risk severity."},
    {"type": "follow_up", "message": "Give a short executive summary of this whole conversation."},
]

# A fixed, opaque PNG payload. We do NOT render a real chart — determinism and a
# stable size matter more than the pixels, and the LLM never needs to read it.
# ~24KB of bytes → ~32KB base64. Same blob for every call (input ignored).
_CHART_BYTES = (b"\x89PNG\r\n\x1a\n" + b"COLMENA_BENCH_FIXED_CHART_PAYLOAD_" * 720)
_CHART_DATA_URI = "data:image/png;base64," + base64.b64encode(_CHART_BYTES).decode("ascii")


def generate_chart(description: str) -> str:  # noqa: ARG001 — input intentionally ignored
    """Return a fixed base64 PNG data URI. Deterministic regardless of input.

    This simulates a chart-generation tool whose raw image output is useless in
    an LLM's text context — Colmena elides it (always-on binary scrubber), the
    other frameworks retain it in history every subsequent turn.
    """
    return _CHART_DATA_URI


CHART_TOOL_NAME = "generate_chart"
CHART_TOOL_DESCRIPTION = (
    "Generate a chart image from a natural-language description. Returns the "
    "chart as a base64 PNG data URI."
)
SYSTEM_MESSAGE = (
    "You are a report analyst assistant. Answer the user's questions about the "
    "attached Q3 2026 report. When the user asks for a chart, call the "
    f"{CHART_TOOL_NAME} tool and then confirm in one short sentence that the "
    "chart was generated — do NOT paste the image data into your reply."
)
