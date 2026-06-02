Australian Tax Resident. Australian Tax System. Australian Tax Year (from July 1st to June 30).

## Start Here

Read **`docs/ai-index.md`** first. It tells you where to find everything in this repository.

## Core Modeling Assumptions
- **Budget 2026 Rules**: 30% non-refundable credit for trust distributions; 30% CGT floor for indexed real gains.
- **CGT Transition (2027)**: Gains accrued until 2027-06-30 utilize the 50% discount; gains thereafter use CPI indexation with no discount.
- **Real Estate Ring-fencing**: Property acquired from 2026-05-13 onwards has negative gearing losses ring-fenced to the RE pool.
- **Iterative Solver**: The simulation uses a 5-pass iterative loop to converge on the equilibrium between taxable income (including CGT) and cash required for annual expenses.

## Key Docs
- `docs/ai-index.md` — master index, where to find what
- `docs/architecture.md` — top-down architecture
- `docs/philosophy.md` — coding standards and principles
- `docs/decisions_made.md` — deliberate design decisions and rejected paths
- `docs/directory_structure.md` — every file and its purpose
- `docs/assumptions.md` — all financial/tax modelling assumptions
