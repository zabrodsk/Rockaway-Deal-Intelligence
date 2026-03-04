"""Ranking decision layer stages.

Scores companies on Strategy Fit, Team Quality, and Problem/Upside (0-100 each),
applies confidence adjustment, and computes composite rank with triage buckets.
"""

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agent.common.llm_config import get_llm
from agent.dataclasses.ranking import CompanyRankingResult, DimensionScore
from agent.pipeline.state.investment_story import IterativeInvestmentStoryState
from agent.pipeline.state.schemas import DimensionScoreOutput
from agent.prompt_library.manager import get_prompt


# Aspect-to-dimension mapping: general_company -> strategy_fit, team -> team, market+product -> upside
DIMENSION_ASPECTS = {
    "strategy_fit": ["general_company"],
    "team": ["team"],
    "upside": ["market", "product"],
}


def _group_qa_by_dimension(
    all_qa_pairs: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group Q&A pairs by ranking dimension."""
    grouped: dict[str, list[dict[str, Any]]] = {
        "strategy_fit": [],
        "team": [],
        "upside": [],
    }
    for qa in all_qa_pairs:
        aspect = qa.get("aspect") or ""
        if aspect in DIMENSION_ASPECTS["strategy_fit"]:
            grouped["strategy_fit"].append(qa)
        elif aspect in DIMENSION_ASPECTS["team"]:
            grouped["team"].append(qa)
        elif aspect in DIMENSION_ASPECTS["upside"]:
            grouped["upside"].append(qa)
    return grouped


def _format_qa_block(qa_pairs: list[dict[str, Any]]) -> str:
    """Format Q&A pairs for the prompt."""
    if not qa_pairs:
        return "No relevant Q&A pairs available."
    lines = []
    for i, qa in enumerate(qa_pairs):
        q = qa.get("question", "")
        a = qa.get("answer", "")
        lines.append(f"Q{i+1}: {q}\nA{i+1}: {a}")
    return "\n---\n".join(lines)


def _score_dimension(
    dimension: str,
    qa_pairs: list[dict[str, Any]],
    company_summary: str,
    vc_context: str,
    prompt_overrides: dict[str, Any] | None,
) -> DimensionScore:
    """Score a single dimension via LLM."""
    qa_block = _format_qa_block(qa_pairs)
    llm = get_llm(temperature=0.0)
    llm_structured = llm.with_structured_output(DimensionScoreOutput)

    if dimension == "strategy_fit":
        system_prompt = get_prompt("ranking.strategy_fit.system", prompt_overrides)
        user_prompt = get_prompt("ranking.strategy_fit.user", prompt_overrides)
        vc_block = vc_context.strip() if vc_context else "Not provided."
        user_content = user_prompt.format(
            company_summary=company_summary,
            vc_context=vc_block,
            qa_block=qa_block,
        )
    elif dimension == "team":
        system_prompt = get_prompt("ranking.team.system", prompt_overrides)
        user_prompt = get_prompt("ranking.team.user", prompt_overrides)
        user_content = user_prompt.format(
            company_summary=company_summary,
            qa_block=qa_block,
        )
    else:  # upside
        system_prompt = get_prompt("ranking.upside.system", prompt_overrides)
        user_prompt = get_prompt("ranking.upside.user", prompt_overrides)
        user_content = user_prompt.format(
            company_summary=company_summary,
            qa_block=qa_block,
        )

    try:
        output: DimensionScoreOutput = llm_structured.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_content),
            ]
        )
    except Exception:
        return DimensionScore(
            dimension=dimension,
            raw_score=0.0,
            confidence=0.0,
            evidence_count=len(qa_pairs),
            evidence_snippets=[],
            critical_gaps=["Scoring failed due to LLM error"],
        )

    return DimensionScore(
        dimension=dimension,
        raw_score=output.raw_score,
        confidence=output.confidence,
        evidence_count=output.evidence_count,
        evidence_snippets=output.evidence_snippets[:3],
        critical_gaps=output.critical_gaps,
    )


def score_company_dimensions(
    state: IterativeInvestmentStoryState,
) -> dict[str, Any]:
    """Score the company on Strategy Fit, Team Quality, and Upside.

    Groups Q&A pairs by dimension, calls LLM for each, and builds
    DimensionScore objects with confidence-adjusted scores.
    """
    company_summary = state.company.get_company_summary()
    grouped = _group_qa_by_dimension(state.all_qa_pairs)

    dimension_scores: list[DimensionScore] = []

    for dim in ("strategy_fit", "team", "upside"):
        qa_pairs = grouped.get(dim, [])
        score = _score_dimension(
            dimension=dim,
            qa_pairs=qa_pairs,
            company_summary=company_summary,
            vc_context=state.vc_context or "",
            prompt_overrides=state.prompt_overrides,
        )
        dimension_scores.append(score)

    strategy_adj = next((s.adjusted_score for s in dimension_scores if s.dimension == "strategy_fit"), 0.0)
    team_adj = next((s.adjusted_score for s in dimension_scores if s.dimension == "team"), 0.0)
    upside_adj = next((s.adjusted_score for s in dimension_scores if s.dimension == "upside"), 0.0)

    result = CompanyRankingResult(
        company_name=state.company.name,
        slug=state.slug or state.company.name,
        strategy_fit_score=strategy_adj,
        team_score=team_adj,
        upside_score=upside_adj,
        dimension_scores=dimension_scores,
    )
    return {"ranking_result": result}


def compute_composite_rank(
    state: IterativeInvestmentStoryState,
) -> dict[str, Any]:
    """Compute composite score, bucket, and tie-breakers.

    Uses equal weights (1/3 each). Assigns priority_review, watchlist, or low_priority.
    """
    result = state.ranking_result
    if not result:
        return {}

    strategy_adj = result.strategy_fit_score
    team_adj = result.team_score
    upside_adj = result.upside_score

    composite = (1 / 3) * strategy_adj + (1 / 3) * team_adj + (1 / 3) * upside_adj
    result.composite_score = round(composite, 2)

    scores = [result.strategy_fit_score, result.team_score, result.upside_score]
    result.min_dimension_score = min(scores) if scores else 0.0

    if result.dimension_scores:
        result.avg_confidence = sum(s.confidence for s in result.dimension_scores) / len(
            result.dimension_scores
        )
        result.critical_gaps_count = sum(len(s.critical_gaps) for s in result.dimension_scores)
    else:
        result.avg_confidence = 0.0
        result.critical_gaps_count = 0

    if result.composite_score >= 75 and result.min_dimension_score >= 55:
        result.bucket = "priority_review"
    elif result.composite_score >= 60:
        result.bucket = "watchlist"
    else:
        result.bucket = "low_priority"

    return {"ranking_result": result}
