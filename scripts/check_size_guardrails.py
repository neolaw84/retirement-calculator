"""Enforce size guardrails for Python source files.

This check implements a "ratchet" policy:
- Default guidelines: function <= 60 lines, module <= 300 lines.
- Existing documented exceptions are allow-listed with current ceilings.
- New code must not introduce new unapproved exceptions.
- Existing exceptions must not grow beyond their current baseline.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

MAX_FUNCTION_LINES = 60
MAX_MODULE_LINES = 300

# Baseline file exceptions (documented deliberate exceptions — see docs/decisions_made.md D25).
ALLOWED_MODULE_EXCEPTIONS: dict[str, int] = {
    # simulate() orchestrates 20+ phase functions; unavoidably long. See D25.
    "src/retirement_calculator/simulation/__init__.py": 270,
}

# Baseline function exceptions (documented deliberate exceptions — see docs/decisions_made.md D25).
ALLOWED_FUNCTION_EXCEPTIONS: dict[tuple[str, str], int] = {
    # simulate() is an inherent orchestrator; splitting further adds worse complexity. See D25.
    ("src/retirement_calculator/simulation/__init__.py", "simulate"): 230,
    # _build_year_record assembles 64 key-value output columns; pure data with no logic. See D25.
    ("src/retirement_calculator/simulation/_year_record.py", "_build_year_record"): 115,
    # cgt_on_parcel has a 29-line docstring; function body is ~33 lines. See D25.
    ("src/retirement_calculator/tax/cgt.py", "cgt_on_parcel"): 65,
}


@dataclass
class Violation:
    kind: str
    path: str
    name: str
    lines: int
    limit: int


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _function_violations(path: Path, source: str) -> list[Violation]:
    tree = ast.parse(source)
    violations: list[Violation] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.scope: list[str] = []

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self.scope.append(node.name)
            self.generic_visit(node)
            self.scope.pop()

        def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            qual = ".".join(self.scope + [node.name]) if self.scope else node.name
            lines = node.end_lineno - node.lineno + 1  # type: ignore[operator]
            if lines > MAX_FUNCTION_LINES:
                rel = _relative(path)
                key = (rel, qual)
                if key in ALLOWED_FUNCTION_EXCEPTIONS:
                    allowed = ALLOWED_FUNCTION_EXCEPTIONS[key]
                    if lines > allowed:
                        violations.append(
                            Violation("function", rel, qual, lines, allowed)
                        )
                else:
                    violations.append(
                        Violation("function", rel, qual, lines, MAX_FUNCTION_LINES)
                    )
            self.scope.append(node.name)
            self.generic_visit(node)
            self.scope.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._visit_function(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._visit_function(node)

    Visitor().visit(tree)
    return violations


def _module_violations(path: Path, source: str) -> list[Violation]:
    rel = _relative(path)
    line_count = len(source.splitlines())
    if line_count <= MAX_MODULE_LINES:
        return []

    if rel in ALLOWED_MODULE_EXCEPTIONS:
        allowed = ALLOWED_MODULE_EXCEPTIONS[rel]
        if line_count <= allowed:
            return []
        return [Violation("module", rel, "<module>", line_count, allowed)]

    return [Violation("module", rel, "<module>", line_count, MAX_MODULE_LINES)]


def main() -> int:
    if not SRC_ROOT.exists():
        print("No src/ directory found; skipping size guardrails.")
        return 0

    violations: list[Violation] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        violations.extend(_module_violations(path, source))
        violations.extend(_function_violations(path, source))

    if not violations:
        print("Size guardrails passed.")
        return 0

    print("Size guardrails failed:")
    for v in violations:
        label = f"{v.path}:{v.name}" if v.name != "<module>" else v.path
        print(f"- {v.kind} {label} has {v.lines} lines (limit {v.limit})")
    print("\nDocument any intentional exception in docs/decisions_made.md,")
    print("then add it to scripts/check_size_guardrails.py with a baseline ceiling.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
