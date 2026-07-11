"""Prompts for the analysis stage, mapped to the Business Analysis Template.

Kept in one place so they can be versioned. Store `prompt_version` alongside any
row you persist so results can be re-generated when prompts improve.
"""
from __future__ import annotations

PROMPT_VERSION = "2024-12-analysis-v1"

SYSTEM_PROMPT = """\
You are an equity research analyst. You are given the transcript of a company's
quarterly earnings conference call (concall). Extract STRUCTURED, FACTUAL data only.
Rules:
- Never invent numbers. If a value is not stated, leave it null.
- For every metric, guidance and red flag, include the VERBATIM sentence from the
  transcript in `raw_quote`. If you cannot cite it, do not include it.
- `guidance` = any forward-looking commitment (targets, expected growth, capex
  plans, margin goals, timelines). Capture the target metric, value, and the
  fiscal_year/quarter by which management expects it.
- `red_flags` = governance / balance-sheet warning signs (rising debt, stretched
  receivables, promoter pledging/selling, auditor issues, related-party deals,
  repeated guidance misses, complex subsidiaries).
- Score all 10 sections of the Business Analysis Template from 0-10 (be strict):
  1 Business simplicity, 2 Revenue growth, 3 Profit growth, 4 Return on capital,
  5 Debt safety, 6 Moat, 7 Management quality, 8 Industry opportunity,
  9 Valuation, 10 Red flags & governance.
Respond ONLY with JSON conforming to the provided schema.
"""

USER_TEMPLATE = """\
Company: {company_name} ({ticker})
Period: FY{fiscal_year} Q{quarter}

Transcript:
\"\"\"
{transcript_text}
\"\"\"
"""


def build_messages(company_name: str, ticker: str, fiscal_year: int, quarter: int, text: str):
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": USER_TEMPLATE.format(
                company_name=company_name,
                ticker=ticker,
                fiscal_year=fiscal_year,
                quarter=quarter,
                transcript_text=text[:120_000],
            ),
        },
    ]
