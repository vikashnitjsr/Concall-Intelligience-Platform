"""LLM client abstraction.

Two implementations:
* StubLLM      - deterministic, offline. Produces plausible structured output from
                 simple heuristics so the whole pipeline runs with no API keys.
* AzureOpenAILLM - real provider using JSON-schema function calling.

Select via settings.llm_provider.
"""
from __future__ import annotations

import hashlib
import re
from typing import Protocol

from app.config import settings
from app.schemas import (
    GuidanceOut,
    MetricOut,
    RedFlagOut,
    SectionScoreOut,
    TranscriptAnalysis,
    TEMPLATE_SECTIONS,
)


class LLMClient(Protocol):
    def analyze(
        self, *, company_name: str, ticker: str, fiscal_year: int, quarter: int, text: str
    ) -> TranscriptAnalysis: ...


def _seed(*parts: object) -> int:
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(h[:8], 16)


class StubLLM:
    """Deterministic offline analyzer.

    It pulls a few real numbers out of the text when present (so demos look alive)
    and otherwise derives stable pseudo-random values from a hash of the inputs, so
    results are reproducible across runs.
    """

    _GUIDANCE_RE = re.compile(
        r"[^.]*\b(expect|guidance|target|aim|plan|will|by\s+FY|next\s+year|going\s+forward)\b[^.]*\.",
        re.IGNORECASE,
    )
    _REDFLAG_RE = re.compile(
        r"[^.]*\b(debt|pledge|receivabl|litigation|delay|shortfall|impair|write-off|resign)\w*[^.]*\.",
        re.IGNORECASE,
    )
    _NUM_RE = re.compile(r"(revenue|ebitda|pat|margin)[^.\d]{0,40}?([\d,]+(?:\.\d+)?)\s*(%|cr|crore)?",
                         re.IGNORECASE)

    def analyze(self, *, company_name, ticker, fiscal_year, quarter, text) -> TranscriptAnalysis:
        seed = _seed(ticker, fiscal_year, quarter)
        rnd = lambda lo, hi, salt=0: lo + (_seed(seed, salt) % 1000) / 1000 * (hi - lo)

        metrics: list[MetricOut] = []
        for m in list(self._NUM_RE.finditer(text))[:8]:
            name = m.group(1).lower().replace(" ", "_")
            try:
                val = float(m.group(2).replace(",", ""))
            except ValueError:
                continue
            metrics.append(MetricOut(name=name, value_numeric=val,
                                     unit=(m.group(3) or None), raw_quote=m.group(0).strip()))
        if not metrics:
            metrics.append(MetricOut(name="revenue", value_numeric=round(rnd(500, 5000), 1),
                                     unit="cr", yoy_pct=round(rnd(-5, 25, 1), 1),
                                     raw_quote="(stub) revenue reference not found in text"))

        guidance: list[GuidanceOut] = []
        for i, m in enumerate(self._GUIDANCE_RE.finditer(text)):
            if i >= 3:
                break
            tq = quarter % 4 + 1
            tfy = fiscal_year + (1 if quarter == 4 else 0)
            guidance.append(GuidanceOut(
                category="revenue" if i == 0 else "margin",
                metric_name="revenue_growth" if i == 0 else "ebitda_margin",
                direction="up",
                target_value=round(rnd(10, 20, i + 2), 1),
                target_unit="%",
                target_fiscal_year=tfy,
                target_quarter=tq,
                raw_quote=m.group(0).strip()[:400],
                confidence=0.6,
            ))

        red_flags: list[RedFlagOut] = []
        for i, m in enumerate(self._REDFLAG_RE.finditer(text)):
            if i >= 3:
                break
            red_flags.append(RedFlagOut(type="balance_sheet", severity="medium",
                                        description="Potential concern detected in commentary.",
                                        raw_quote=m.group(0).strip()[:400]))

        section_scores = [
            SectionScoreOut(section_no=no, section_name=name,
                            score_0_10=round(4 + rnd(0, 6, no), 1),
                            rationale="(stub heuristic score)")
            for no, name in TEMPLATE_SECTIONS
        ]

        return TranscriptAnalysis(
            business_summary=f"{company_name} — auto summary (stub).",
            sentiment=round(rnd(-0.3, 0.7, 99), 2),
            aggression=round(rnd(0.2, 0.9, 100), 2),
            metrics=metrics,
            guidance=guidance,
            red_flags=red_flags,
            section_scores=section_scores,
        )


class AzureOpenAILLM:
    """Real provider. Requires `openai` package + Azure OpenAI env vars."""

    def analyze(self, *, company_name, ticker, fiscal_year, quarter, text) -> TranscriptAnalysis:
        from openai import AzureOpenAI  # imported lazily

        from app.llm.prompts import build_messages

        client = AzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
        )
        messages = build_messages(company_name, ticker, fiscal_year, quarter, text)
        resp = client.chat.completions.create(
            model=settings.azure_openai_deployment,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0,
        )
        return TranscriptAnalysis.model_validate_json(resp.choices[0].message.content)


class OpenAILLM:
    """Real provider using OpenAI structured outputs (guaranteed schema)."""

    def analyze(self, *, company_name, ticker, fiscal_year, quarter, text) -> TranscriptAnalysis:
        from openai import OpenAI  # imported lazily

        from app.llm.prompts import build_messages

        client = OpenAI(api_key=settings.openai_api_key)
        messages = build_messages(company_name, ticker, fiscal_year, quarter, text)
        try:
            # Structured Outputs: model is forced to return valid TranscriptAnalysis.
            completion = client.beta.chat.completions.parse(
                model=settings.openai_model,
                messages=messages,
                response_format=TranscriptAnalysis,
                temperature=0,
            )
            parsed = completion.choices[0].message.parsed
            if parsed is not None:
                return parsed
        except Exception:
            # Fallback to JSON mode if the model/SDK doesn't support parse().
            pass
        resp = client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0,
        )
        return TranscriptAnalysis.model_validate_json(resp.choices[0].message.content)


class AgentFileLLM:
    """Analysis produced by an agent (me) and dropped as JSON on disk.

    Reads data/analyses/{TICKER}_{FY}Q{Q}.json (a serialized TranscriptAnalysis).
    This lets the platform run with *real* analysis and NO external API key: the
    agent reads the transcript in-session, writes the JSON, and the pipeline
    consumes it like any other provider.
    """

    def analyze(self, *, company_name, ticker, fiscal_year, quarter, text) -> TranscriptAnalysis:
        import os

        path = os.path.join("data", "analyses", f"{ticker}_{fiscal_year}Q{quarter}.json")
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"No agent analysis found at {path}. Extract the transcript, have the "
                f"agent write this JSON, then re-run."
            )
        with open(path, "r", encoding="utf-8") as fh:
            return TranscriptAnalysis.model_validate_json(fh.read())


def get_llm() -> LLMClient:
    if settings.llm_provider == "openai":
        return OpenAILLM()
    if settings.llm_provider == "azure_openai":
        return AzureOpenAILLM()
    if settings.llm_provider == "agent":
        return AgentFileLLM()
    return StubLLM()
