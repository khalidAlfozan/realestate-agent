# realestate-agent

[![ci](https://github.com/khalidAlfozan/realestate-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/khalidAlfozan/realestate-agent/actions/workflows/ci.yml)

A single-user investment-analyst agent for the Warsaw residential rental market. Paste an Otodom listing URL and get back a structured investment memo: yield analysis, comparables, neighbourhood context, photo-based condition assessment, and a buy/walk recommendation with a confidence score — the half-day of analyst work compressed into a few minutes.

## What it does

- Accepts a Warsaw residential property listing (Otodom URL; pasted listing text as fallback).
- Runs an agentic loop (Claude Sonnet 4.6, hand-rolled with the Anthropic Python SDK and tool-use API) that calls deterministic tools to gather and reason over data.
- Tools the agent can call:
  - `get_property_details(url)` — scrape price (PLN), m², rooms, floor, build year, ownership form, community fee, heating type, location, photos.
  - `find_comparable_properties(...)` — pull recent listings and sales in the same Warsaw district.
  - `get_neighbourhood_stats(...)` — demographics, income, rental trends from GUS (Polish national statistics) and the Warsaw Open Data API.
  - `analyse_listing_photos(image_urls)` — multimodal condition/age/renovation assessment.
  - `calculate_financials(...)` — gross yield, net yield (after czynsz administracyjny), cap rate, 10-year IRR with interest-rate sensitivity. Pure Python, not LLM math.
  - `search_market_reports(query)` — RAG over a curated corpus of Polish real estate research (NBP housing reports, AMRON-SARFiN, CBRE Poland, JLL Poland, Knight Frank Poland, Otodom Analytics, ING Bank Śląski research).
- Outputs a markdown investment memo with a fixed seven-section template:
  1. Property summary
  2. Neighbourhood context
  3. Condition assessment
  4. Comparables (sales and rentals)
  5. Financial analysis (yield, cap rate, 10-year IRR)
  6. Risks and sensitivities
  7. Recommendation (buy / walk) with confidence score and reasoning

## What it doesn't do

- **Not multi-tenant.** One user, one local instance.
- **Not multi-city.** Warsaw only.
- **Not multi-asset-type.** Long-term residential rentals only — no short-lets/Airbnb, no commercial, no new-build off-plan, no land.
- **No anti-bot arms race.** If Otodom blocks scraping, fall back to user-pasted text. Don't burn the v1 budget on scraper hardening.
- **No transactional features.** No saved searches, no alerts, no portfolio tracking, no user accounts, no payments.
- **No fine-tuning.** Off-the-shelf Claude models with prompting and tools.
- **No agent framework.** Hand-rolled loop — no LangChain, LangGraph, or similar in v1.

## Done (v1 acceptance criteria)

v1 ships when **all** of the following are true:

1. **End-to-end demo:** From a Warsaw Otodom URL, the Streamlit app produces a complete seven-section memo in under three minutes per run.
2. **Tools in place:** All six tools above are implemented and callable by the agent loop.
3. **RAG corpus loaded:** ≥30 Polish market-report PDFs chunked, embedded, and queryable via pgvector.
4. **Eval harness:** ≥25 manually-scored Warsaw properties in `evals/cases.json`, `python evals/run_evals.py` runs the agent on each and reports recommendation accuracy and section-level quality scores.
5. **Cost + latency logging:** Every run emits structured JSON logs with per-call token counts, dollar cost, latency, and tool-call counts.
6. **Deployed:** Reachable at a public URL (Railway or Fly.io) with the Anthropic key in env, not committed.
7. **README explains the choices:** Why hand-rolled, why pgvector, why fail-soft scraping, why these models — the document a hiring manager would actually read.

Stretch (post-v1, only if time): MCP server packaging of the tools so other agents can consume them.

## Stack

Python 3.13 · Anthropic Python SDK · Claude Sonnet 4.6 (agent) + Claude Haiku 4.5 (classification) · pgvector on Postgres · `httpx` + `BeautifulSoup` · Streamlit · pytest · structured JSON logs.

## Code quality

CI runs the following on every PR — see `.github/workflows/ci.yml`:

| Tool | What it catches |
|---|---|
| `ruff check` | Style, imports, complexity (`C90`, max 10), naming (`N`), security (`S` / bandit), pytest patterns (`PT`), unused args (`ARG`), simplifications (`SIM`), modernisation (`UP`) |
| `ruff format --check` | Formatting drift |
| `pyright` (basic) | Type errors |
| `deptry` | Unused / missing / transitive deps |
| `pytest --cov` | Tests + branch coverage; CI fails if total drops below **90%** |
| `CodeQL` | GitHub-native SAST (security analysis). Results in the repo's **Security** tab. Runs on every PR + weekly schedule. |


## Commit conventions

PR titles must follow [Conventional Commits](https://www.conventionalcommits.org/) — enforced in CI by `.github/workflows/pr-title.yml`. Since `main` is squash-merged, the PR title becomes the commit message on `main`, so this gives the project a machine-readable history without forcing every PR-branch commit to comply.

**Format:** `<type>(<optional scope>): <subject>`

| Type | When |
|---|---|
| `feat` | New functionality (new tool, new memo section) |
| `fix` | Bug fix |
| `refactor` | Restructure without behaviour change |
| `docs` | README, comments, prompt files |
| `test` | Test-only changes |
| `chore` | Housekeeping, deps |
| `ci` | CI / workflow config |
| `build` | `pyproject.toml`, `uv.lock`, build system |
| `revert` | Revert a previous commit |

Scopes are optional and free-form (`feat(tools): ...`, `feat(prompts): ...`). Subject lines: imperative mood, no trailing period.

**Examples**

```
feat(tools): add find_comparable_properties + Pydantic models
fix(config): make ANTHROPIC_API_KEY validation lazy
refactor: layer CLI out of agent.py and type the tool registry
ci: enforce conventional commit titles on PRs
build(deps): bump anthropic to 0.101.0
```

Breaking changes use `!` after the type/scope (`feat(api)!: ...`) or a `BREAKING CHANGE:` footer in the body.
