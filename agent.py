from __future__ import annotations

import json
import os
from typing import Iterable

import pandas as pd
from pydantic import BaseModel, Field


SYSTEM_PROMPT = """You are the Finance Mapping component of a Budget vs Actual pipeline.
Python performs all financial calculations, reconciliation, aggregation and Excel generation.
Your only task is to classify ambiguous Operating Non-Labour patterns that deterministic rules could not map.

Rules:
- Never map Labour, Depreciation, Interest/accrual, or other excluded categories.
- Do not reassign Management Codes.
- GL code alone is insufficient for mixed-purpose accounts; use DESCRIPTION.
- Never force a mapping. If evidence is insufficient, return Unmapped / Review Required.
- A proposed mapping remains provisional unless Finance explicitly validated it.

Allowed mapping_status values:
- PoC Proposed
- Unmapped / Review Required

Return only structured decisions for the supplied candidate IDs.
"""


class MappingDecision(BaseModel):
    candidate_id: str
    proposed_budget_account: str | None = None
    proposed_budget_category: str | None = None
    mapping_status: str = Field(pattern=r"^(PoC Proposed|Unmapped / Review Required)$")
    confidence: str = Field(pattern=r"^(High|Medium|Low)$")
    rationale: str


class MappingDecisionList(BaseModel):
    decisions: list[MappingDecision]


def _fallback(candidates: pd.DataFrame) -> dict[str, MappingDecision]:
    out = {}
    for row in candidates.itertuples(index=False):
        cid = str(row.CANDIDATE_ID)
        out[cid] = MappingDecision(
            candidate_id=cid,
            mapping_status="Unmapped / Review Required",
            confidence="Low",
            rationale="No deterministic mapping rule and LLM mapping unavailable or inconclusive.",
        )
    return out


def map_ambiguous_patterns(candidates: pd.DataFrame, budget_categories: pd.DataFrame) -> dict[str, MappingDecision]:
    """Map only unique ambiguous patterns. Safe fallback is Unmapped.

    The model is optional. Set BUDGET_AGENT_USE_LLM=true plus OPENAI_API_KEY and
    BUDGET_AGENT_MODEL to enable it. The pipeline remains deterministic without it.
    """
    if candidates.empty:
        return {}
    if os.getenv("BUDGET_AGENT_USE_LLM", "false").lower() not in {"1", "true", "yes"}:
        return _fallback(candidates)

    try:
        from langchain_openai import ChatOpenAI

        model = os.getenv("BUDGET_AGENT_MODEL", "gpt-4.1")
        llm = ChatOpenAI(model=model, temperature=0)
        structured = llm.with_structured_output(MappingDecisionList)

        budget_payload = budget_categories[["BUDGET_ACCOUNT", "BUDGET_CATEGORY"]].drop_duplicates().to_dict("records")
        candidate_payload = candidates[
            ["CANDIDATE_ID", "MANAGEMENT_CODE", "LIB4", "ACCOUNT_CODE", "DESCRIPTION"]
        ].to_dict("records")

        user_message = (
            "Available Reference Budget categories:\n"
            + json.dumps(budget_payload, ensure_ascii=False)
            + "\n\nAmbiguous transaction patterns:\n"
            + json.dumps(candidate_payload, ensure_ascii=False)
        )
        result = structured.invoke([
            ("system", SYSTEM_PROMPT),
            ("user", user_message),
        ])
        by_id = {d.candidate_id: d for d in result.decisions}
        fallback = _fallback(candidates)
        fallback.update(by_id)
        return fallback
    except Exception:
        return _fallback(candidates)
