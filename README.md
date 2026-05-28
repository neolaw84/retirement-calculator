# retirement-calculator

> Retirement Calculator for Australian Tax Resident to FIRE

[![PyPI version](https://badge.fury.io/py/retirement-calculator.svg)](https://badge.fury.io/py/retirement-calculator)
[![Documentation](https://img.shields.io/badge/docs-gh--pages-blue)](https://neolaw84.github.io/retirement-calculator/)

## Installation

```bash
pip install retirement-calculator
```

Or install the latest development build directly from GitHub Releases:

```bash
pip install https://github.com/neolaw84/retirement-calculator/releases/latest/download/retirement-calculator-latest-py3-none-any.whl
```

## Quick Start

```python
import retirement-calculator

# Your code here
```

## Development

### Set up the environment

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev,docs]"
```

### Bootstrap GitHub branch rules and labels

Use the script below once after creating a new repository from this template.

```bash
python -m venv script-venv
source script-venv/bin/activate   # Windows: script-venv\Scripts\activate
pip install --upgrade pip
pip install -r scripts/requirements-github-rules.txt

export GITHUB_TOKEN="<your-admin-token>"
python scripts/setup_github_rules.py --repo neolaw84/retirement-calculator
```

The script configures:
- branch protection for `main` and `dev`
- required labels (`bump:major`, `bump:minor`, `bump:patch`)
- Actions workflow permissions (`GITHUB_TOKEN` read/write)

### Run tests

```bash
pytest
```

### Build documentation locally

```bash
mkdocs serve
```

## Contributing

1. Fork the repository and create your feature branch from **dev**.
2. Add tests for every new behaviour.
3. Open a Pull Request targeting **dev** — CI will gate on tests + coverage.
4. Label your PR with `bump:major`, `bump:minor` (default), or `bump:patch` to control the version bump when it is eventually merged to **main**.

### Versioning

This project uses [git-tag-based versioning](https://setuptools-scm.readthedocs.io/).
There is no `version` field in `pyproject.toml`.

- On feature branches the installed version will have a dev suffix (e.g. `1.2.0.dev3+gabcdef0`). This is intentional.
- The final version is set automatically when a PR is merged to **main**: `release.yml` reads the bump label, computes the next semver, creates an annotated git tag, and builds the release artefacts.
- To preview the next tag locally: `python scripts/bump_version.py minor --dry-run`
- To create the initial tag on a brand-new repo: `git tag v0.1.0 && git push origin v0.1.0`

## License

Apache-2.0 — see [LICENSE](LICENSE) for details.
