# Changelog

All notable changes to this project will be documented in this file.

## [0.0.3] - 2026-03-04

### Added

- **Executive Summary**: Human-readable summaries for the three scoring dimensions (Strategy Fit, Team, Potential), plus Key Points and Red Flags sections
  - New pipeline stage `generate_executive_summary` runs after `compute_composite_rank`
  - `CompanyRankingResult` now includes: `strategy_fit_summary`, `team_summary`, `potential_summary`, `key_points`, `red_flags`
  - UI renders Summary, KEY POINTS, and RED FLAGS (N) in both single-company and batch result cards
  - Excel export includes key_points and red_flags columns

### Changed

- Extended ranking prompts with `EXECUTIVE_SUMMARY_SYSTEM` and `EXECUTIVE_SUMMARY_USER`
- Added `ExecutiveSummaryOutput` Pydantic schema for LLM structured output

## [0.0.2] - 2026-03-04

### Added

- Answer-triggered Perplexity web search: only queries the API when the LLM answer indicates no evidence (e.g. "Unknown from provided documents")
- `WEB_SEARCH_TRIGGER` env var: `answer` (default) or `no_chunks` for trigger mode
- `_answer_indicates_no_evidence()` pattern matching for lack-of-evidence detection

### Changed

- Default LLM: Gemini 3.1 Flash-Lite (`gemini-3-flash-lite-preview`)
- Evidence answering flow: run grounded LLM call first, then conditionally call Perplexity when answer indicates no evidence
- Web app, Specter ingest, ranking stage, prompt library integrations
