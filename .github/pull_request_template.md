## Summary

Describe the change and why it is needed.

## Spec + TDD Checklist (required)

- [ ] I updated `docs/specs.md` (or confirmed no spec change is needed and explained why).
- [ ] I added/updated tests for the expected behaviour.
- [ ] Tests were written/updated before or alongside implementation (red -> green -> refactor).

## SOLID + Size Checklist (required)

- [ ] The change preserves module responsibilities (SRP) and avoids cross-layer coupling.
- [ ] New behaviour was added by extension where practical (OCP), not by breaking existing contracts.
- [ ] No new Python module exceeds 300 lines unless explicitly documented as an exception.
- [ ] No new function exceeds 60 lines unless explicitly documented as an exception.
- [ ] Any exception rationale is recorded in `docs/decisions_made.md`.

## Documentation Checklist

- [ ] I updated `docs/assumptions.md` for any modelling assumption changes.
- [ ] I updated `docs/decisions_made.md` for any deliberate design decisions or exceptions.
- [ ] I updated `docs/directory_structure.md` if module/file structure changed.
