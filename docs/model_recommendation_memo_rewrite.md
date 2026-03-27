# Recommendation: Validate Scoring Stability Before Changing Model Strategy

## Executive Summary
The most important issue in the current model strategy is not which model should replace GPT-5 in each stage. It is whether evaluation and ranking are operating with the intended level of scoring consistency. The current draft identifies a likely risk that GPT-5 temperature may be forced to `1.0`, which could reduce repeatability in the phases where stable scoring matters most. If that behavior is active in production, model comparisons built on top of it are not yet decision-grade. The recommended next step is to verify or fix that behavior first, then run a focused benchmark before approving broader model changes.

## What We Found
The current recommendation highlights a potentially important implementation issue: GPT-5 temperature settings may be overridden globally rather than respected at the pipeline-stage level. If true, that means evaluation and ranking may be running with more variability than intended. This does not yet prove that GPT-5 is the wrong model for those stages, but it does mean current conclusions about phase-by-phase model fit should be treated as provisional until the scoring setup is validated.

## Why It Matters
- Evaluation quality depends on scoring consistency. If repeated runs can produce materially different scores for the same inputs, the resulting argument selection process becomes less reliable.
- Ranking quality depends on comparability across companies and across time. Variability in the scoring layer can weaken confidence in relative rankings and investment decisions.
- Leadership should be able to distinguish between a model-selection problem and a configuration problem. Addressing the latter first is the fastest path to a credible recommendation.

## Near-Term Recommendation

| Pipeline phase | Current model | Near-term recommendation | Why |
| --- | --- | --- | --- |
| Decomposition | GPT-5 | Benchmark Gemini 2.5 Pro as a candidate; do not switch yet | It may improve structured decomposition, but that should be validated rather than assumed. |
| Q&A | Gemini Flash Lite | Keep current setup unless testing shows a clear quality gap | The current draft does not present enough evidence to justify a change here. |
| Generation | GPT-5 | Keep GPT-5 as the default for now | This is the phase where higher variability may be acceptable if it supports stronger argument generation. |
| Evaluation | GPT-5 | Verify temperature behavior first, then test Claude Sonnet 4 as the primary alternative | Claude Sonnet 4 is a credible candidate for rubric-based evaluation, but the recommendation should follow a stable baseline. |
| Ranking | GPT-5 | Verify temperature behavior first, then test Claude Opus 4 only if quality gain justifies cost | Ranking volume is low enough that a premium model may be viable, but only if it delivers a meaningful decision-quality benefit. |

## Recommendation
Do not finalize a broad phase-by-phase model migration yet. First, confirm whether GPT-5 temperature is actually being forced to `1.0` in the live path and whether that behavior is intentional, API-driven, or accidental. If the issue is confirmed, correct it or otherwise establish a stable scoring configuration. Once that baseline is in place, run a focused benchmark to compare current performance against Claude Sonnet 4 for evaluation, Claude Opus 4 for ranking, and Gemini 2.5 Pro for decomposition.

## Next Step
Run a short benchmark designed to answer four questions:
- Does repeated scoring of the same input produce acceptably stable results?
- Do alternative models materially improve output quality for their target phases?
- What is the latency impact of any proposed change?
- What is the cost impact relative to the quality improvement?

The output of that benchmark should be a final recommendation on whether to keep the current setup, selectively replace models in specific phases, or retain GPT-5 more broadly after the scoring configuration is corrected.
