# AI Agent Index

> **Start here.** This file tells you where to find what in this repository.
> It is intentionally brand-agnostic and applies to any coding agent (GitHub Copilot, Claude, etc.).

---

## What is this project?

A year-by-year retirement simulation library for **Australian tax residents** pursuing FIRE. It incorporates the May 12, 2026 Federal Budget tax reforms. The ultimate goal is a Gradio/Streamlit app on HuggingFace Spaces.

---

## Before You Write Any Code

1. Read **`docs/decisions_made.md`** — do not re-explore paths that have been deliberately rejected.
2. Read **`docs/assumptions.md`** — do not change tax/financial logic without understanding the documented assumptions.
3. Read **`docs/philosophy.md`** — understand the coding standards and principles.

---

## Where to Find What

### "What does the system do overall?"
→ `docs/architecture.md`

### "What are the inputs and outputs of simulate()?"
→ `docs/specs.md` (high-level), `docs/simulator.md` (detailed with formulas and examples)

### "What modelling shortcuts / approximations were made?"
→ `docs/assumptions.md`

### "Why was X implemented this way? What was considered and rejected?"
→ `docs/decisions_made.md`

### "Where is the file/module that does X?"
→ `docs/directory_structure.md`

### "What are the coding standards for this project?"
→ `docs/philosophy.md`

### "What bugs have been found and fixed already?"
→ `docs/senior_review_260529_01.md` (10 bugs, first review)
→ `docs/senior_review_260529_02.md` (3 bugs, second review + coverage requirement)

---

## Key Files by Domain

| Domain | File(s) |
|---|---|
| Data models | `src/retirement_calculator/models/__init__.py` |
| Rate functions | `src/retirement_calculator/rates/__init__.py` |
| Income tax, Medicare, Div293, super fund tax | `src/retirement_calculator/tax/__init__.py` |
| CGT (pre/post 2027 Budget rules) | `src/retirement_calculator/tax/cgt.py` |
| Drawdown parcel selection strategies | `src/retirement_calculator/strategies/__init__.py` |
| Main simulation engine | `src/retirement_calculator/simulation/__init__.py` |
| Tests | `tests/` (see `docs/directory_structure.md` for test file purposes) |

---

## Intentional Exclusions (Counted as Fulfilled)

These are deliberate non-modelled items documented in `docs/decisions_made.md` and treated as fulfilled for this project:

| Item | Decision ref |
|---|---|
| Income tax rate changes: 15% (2026), 14% (2027) | D03 |
| Working Australians Tax Offset (WATO, $250 from 2027-28) | D04 |
| $1,000 instant work-related expense deduction (from 2026-27) | D05 |

## Remaining Not Yet Implemented Items

| Item | Decision ref |
|---|---|
| Franking credits on ETF distributions | D21 |
| Age Pension | D24 |
| Depreciation on real estate | D18 |

Do not implement these without reading the related decision entry first. Some have documented prerequisites.

---

## Running the Code

```bash
# Install (editable)
pip install -e ".[dev]"

# Run tests
pytest

# Build docs
mkdocs serve
```

---

## Tax Regime Summary (2025-26 base, Budget 2026 changes)

| Bracket | Rate |
|---|---|
| $0 – $18,200 | Nil |
| $18,201 – $45,000 | 16% (NOTE: 15% from 1 Jul 2026 / 14% from 1 Jul 2027 — NOT YET modelled) |
| $45,001 – $135,000 | 30% |
| $135,001 – $190,000 | 37% |
| $190,001+ | 45% |
| Medicare levy | +2% on all |
| Trust distributions | 30% non-refundable credit |
| CGT (pre-2027 disposal) | 50% discount on nominal gain |
| CGT (post-2027 disposal) | CPI-indexed real gain, 30% minimum rate |
| Negative gearing (property bought ≥ 2026-05-13) | Losses ring-fenced to RE pool |
| Super (accumulation) | 15% on concessional contributions + earnings |
| Super (pension phase) | 0% on earnings and withdrawals |
| Division 293 | +15% on concessional super, income > $250k |

---

## Conventions

- All money amounts in the simulation are **nominal dollars** unless a column name ends in `_real`.
- "Real" means deflated to the simulation's start year (base CPI = 100.0).
- The simulation year runs from `current_year` to `current_year + (99 - current_age)`.
- Australian financial year starts July 1. The simulation uses calendar year as a proxy.
