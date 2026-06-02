# Philosophy

This document records the engineering philosophy that guides development of this codebase. Coding agents must read and respect this before making changes.

---

## 1. Domain First

This is a **financial calculator for Australian tax residents**. Tax law is complex and evolves. All modelling decisions must be traceable to an authoritative source (ATO, legislation, the May 12 2026 Budget papers). When a rule is simplified or approximated, this must be documented in `docs/assumptions.md`.

---

## 2. Spec-Driven Development + TDD

New features follow this order:

1. Write or update the spec in `docs/specs.md` (what should the system do?).
2. Write a failing test that captures the expected behaviour.
3. Implement the minimum code to pass the test.
4. Refactor.

Do not write implementation code without a corresponding spec and test. Do not write tests without first reading the spec.

---

## 3. SOLID Principles

Apply SOLID with pragmatism:

- **Single Responsibility**: Each module/class has one reason to change. `rates` handles randomness. `models` holds data. `tax` does tax math. `strategies` selects parcels. `simulation` orchestrates.
- **Open/Closed**: New rate functions, new drawdown strategies, and new tax regimes should be added by extension, not by modifying existing classes.
- **Liskov Substitution**: All `RateFunction` subclasses are interchangeable. All `DrawdownStrategy` implementors must satisfy the Protocol (same signature, same contract).
- **Interface Segregation**: Keep protocols narrow. `DrawdownStrategy.select_parcels` does one thing. Do not add unrelated methods to shared protocols.
- **Dependency Inversion**: `simulation` depends on the `RateFunction` and `DrawdownStrategy` abstractions, not on concrete implementations.

Exceptions to SOLID are permitted **only with a clearly documented rationale** in `docs/decisions_made.md`.

---

## 4. Size Limits

| Unit | Guideline | Hard Limit |
|---|---|---|
| Function / method | 40–60 lines | — |
| Module (`.py` file) | 200–300 lines | — |

Exceptions are permitted if and only if there is a sound logical or practical argument (e.g. the `simulate()` function is currently very long but is a single coherent algorithm that would become harder to follow if split across many private functions). Any such exception must be noted in `docs/decisions_made.md`.

When refactoring, the first question to ask is: *can this block of logic be a pure function with a descriptive name?*

---

## 5. Pure Functions and Immutable Data

Prefer pure functions over stateful classes. The `tax`, `rates`, and `strategies` layers are almost entirely pure functions. Side effects are confined to the simulation loop (which necessarily mutates parcel state in-place). Do not introduce new stateful classes without good reason.

Dataclasses (not Pydantic) are used for data models. Validation is lightweight (`__post_init__`), not a framework concern.

---

## 6. Readability Over Cleverness

- Comments are written only where the *why* is non-obvious (not the *what*).
- Variable names are verbose and domain-specific (`super_accumulation_balance`, not `sab`).
- Use named constants (e.g. `INDEXATION_START_YEAR`, `MIN_CGT_RATE`) instead of magic numbers.
- Avoid deep nesting; extract helper functions.

---

## 7. Separation of Concerns Between Tax and Simulation

Tax functions (`tax/__init__.py`, `tax/cgt.py`) must remain simulation-agnostic. They take numbers and return numbers. They must not receive `CalculatorConfig` or any simulation state object. The simulation layer is responsible for preparing the right inputs and interpreting the outputs.

---

## 8. Maintainability for AI Agents

This codebase is maintained by AI coding agents. The docs in this `docs/` directory are the primary context source. Agents should:

- Read `docs/ai-index.md` first (tells you where to look for what).
- Read `docs/decisions_made.md` before brainstorming architectural changes.
- Read `docs/assumptions.md` before touching any tax or financial calculation.
- Update `docs/assumptions.md` whenever a new modelling assumption is introduced.
- Update `docs/decisions_made.md` when a deliberate design choice is made.

---

## 9. Test Coverage

The minimum accepted test coverage is **80%** (enforced by `--cov-fail-under=80` in pytest config). Aim for coverage of all conditional branches, not just line coverage. Integration-style simulation tests (full `simulate()` runs) are valued alongside unit tests of individual functions.
