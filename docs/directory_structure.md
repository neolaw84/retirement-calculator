# Directory Structure

This document describes every file and directory in the repository. Read this to find where to look for specific code or docs without resorting to `find` / `grep` searches.

```
retirement-calculator/
│
├── src/
│   └── retirement_calculator/          ← main Python package (importable as `retirement_calculator`)
│       ├── __init__.py                 ← package metadata (__version__, __author__)
│       ├── models/
│       │   └── __init__.py             ← data models: Parcel, AssetAllocation, NREAssetConfig,
│       │                                  TrustAssetConfig, REAssetConfig, DrawdownPolicy
│       ├── rates/
│       │   └── __init__.py             ← rate functions: RateFunction (ABC), ConstantRate,
│       │                                  NormalRate, HistoricalRate
│       ├── tax/
│       │   ├── __init__.py             ← tax calculations: income_tax(), marginal_rate(),
│       │   │                              division_293_tax(), super_fund_tax()
│       │   │                              Tax brackets (2025-26), LITO, Medicare, Div293, Trust credit
│       │   └── cgt.py                  ← CGT calculations: cgt_on_parcel()
│       │                                  Pre-2027 (50% discount) and post-2027 (CPI indexed, 30% floor)
│       ├── strategies/
│       │   └── __init__.py             ← DrawdownStrategy (Protocol), LIFOStrategy, FIFOStrategy,
│       │                                  TaxOptimisedGreedyStrategy, RebalancingStrategy
│       │                                  DrawdownOrchestrator (stub — not yet used by simulate())
│       └── simulation/
│           └── __init__.py             ← CalculatorConfig (dataclass), simulate() function
│                                          Main simulation loop (~1100 lines, see decisions_made D25)
│
├── tests/
│   ├── __init__.py
│   ├── test_sample.py                  ← basic package import / version test
│   ├── test_rates.py                   ← unit tests for ConstantRate, NormalRate, HistoricalRate
│   ├── test_tax.py                     ← unit tests for income_tax, LITO, Div293, super_fund_tax, CGT
│   ├── test_strategies.py              ← unit tests for FIFO, LIFO, TaxOptimised, Rebalancing strategies
│   ├── test_simulation.py              ← integration tests for full simulate() runs (ring-fencing, trust credit)
│   ├── test_simulation_smoke.py        ← smoke tests: simulate() runs without error under various configs
│   ├── test_bridge_phase.py            ← scenario: pre-super-access "bridge" phase (NRE drawdown only)
│   ├── test_pension_phase.py           ← scenario: pension phase with minimum drawdown rates
│   ├── test_coverage_gap.py            ← scenario: funding gap forcing drawdowns
│   ├── test_coverage_boost.py          ← scenario: surplus reinvestment paths
│   └── test_coverage_2026_rebalanced.py ← scenario: rebalancing drawdown strategy with 2026 Budget rules
│
├── docs/
│   ├── ai-index.md                     ← START HERE — where to look for what (all agents)
│   ├── architecture.md                 ← top-down architecture guide (this codebase)
│   ├── philosophy.md                   ← coding principles and rules for this project
│   ├── decisions_made.md               ← deliberate design choices and rejected alternatives
│   ├── directory_structure.md          ← THIS FILE — repo layout and file purposes
│   ├── assumptions.md                  ← all financial/tax modelling assumptions and simplifications
│   ├── specs.md                        ← feature specification (inputs, outputs, tax regime, policies)
│   ├── simulator.md                    ← detailed usage guide and per-year calculation reference
│   ├── senior_review_260529_01.md      ← first architectural review findings (10 bugs + fixes, May 29 2026)
│   ├── senior_review_260529_02.md      ← second architectural review findings (3 bugs + coverage req)
│   ├── index.md                        ← mkdocs homepage (embeds README.md)
│   └── api.md                          ← mkdocs API reference (mkdocstrings)
│
├── configs/
│   └── .gitkeep                        ← placeholder; config files (YAML/JSON scenarios) go here
│
├── notebooks/
│   └── quick_start.ipynb               ← Jupyter notebook: quick start demo of simulate()
│
├── scripts/
│   ├── bump_version.py                 ← compute next semver tag (used by release.yml)
│   ├── setup_github_rules.py           ← one-time script to set branch protection and labels
│   └── strip_notebook_outputs.py       ← strips output cells from notebooks before commit
│
├── .github/
│   ├── copilot-instructions.md         ← GitHub Copilot context (redirects to docs/ai-index.md)
│   └── workflows/
│       ├── ci-dev.yml                  ← CI on pushes to dev branch (tests + coverage)
│       ├── ci-main.yml                 ← CI on pushes to main branch
│       ├── docs.yml                    ← builds and deploys mkdocs to GitHub Pages
│       └── release.yml                 ← auto-tags and releases on merge to main
│
├── pyproject.toml                      ← project metadata, dependencies, pytest config, coverage config
├── mkdocs.yml                          ← MkDocs documentation site configuration
├── README.md                           ← project overview, install, quick start, contributing
└── .gitignore
```

---

## Key Entry Points for Coding Agents

| Task | Where to start |
|---|---|
| Understand overall design | `docs/architecture.md` |
| Add / fix a tax rule | `src/retirement_calculator/tax/__init__.py` or `tax/cgt.py` |
| Add / fix a drawdown strategy | `src/retirement_calculator/strategies/__init__.py` |
| Add / fix simulation logic | `src/retirement_calculator/simulation/__init__.py` |
| Add a new input parameter | `src/retirement_calculator/models/__init__.py` → then update `CalculatorConfig` in `simulation/__init__.py` |
| Add a new rate function | `src/retirement_calculator/rates/__init__.py` |
| Write tests | `tests/` — pick the most relevant test file or create a new one |
| Check modelling assumptions | `docs/assumptions.md` |
| Check a design decision | `docs/decisions_made.md` |
| Understand the output columns | `src/retirement_calculator/simulation/__init__.py` (the `records.append({...})` block near the end) |
