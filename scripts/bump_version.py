#!/usr/bin/env python3
"""Create the next semver git tag locally.

This project uses git-tag-based versioning (setuptools-scm).  There is no
version field in pyproject.toml.  Use this script to preview or create the
next tag on your local branch before pushing.

Usage:
    python scripts/bump_version.py <major|minor|micro|patch> [--dry-run]

Examples:
    python scripts/bump_version.py minor            # tags v1.3.0 locally
    python scripts/bump_version.py patch --dry-run  # prints tag, does nothing

Note: in CI the tag is created automatically by release.yml on merge to main.
"""

from __future__ import annotations

import subprocess
import sys


def latest_tag() -> str:
    """Return the most recent semver tag reachable from HEAD, or v0.0.0."""
    try:
        return subprocess.check_output(
            ["git", "describe", "--tags", "--abbrev=0"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        return "v0.0.0"


def next_tag(bump_type: str) -> str:
    """Calculate the next tag string for the given bump type."""
    current = latest_tag().lstrip("v")
    parts = current.split(".")
    major, minor, micro = int(parts[0]), int(parts[1]), int(parts[2])

    if bump_type == "major":
        major += 1; minor = 0; micro = 0
    elif bump_type == "minor":
        minor += 1; micro = 0
    elif bump_type in ("micro", "patch"):
        micro += 1
    else:
        print(f"ERROR: Unknown bump type '{bump_type}'. Use major, minor, micro, or patch.")
        sys.exit(1)

    return f"v{major}.{minor}.{micro}"


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    bump_type = args[0]
    dry_run = "--dry-run" in args

    tag = next_tag(bump_type)
    current = latest_tag()
    print(f"Current tag : {current}")
    print(f"Next tag    : {tag}")

    if dry_run:
        print("Dry run — no tag created.")
        return

    subprocess.run(
        ["git", "tag", "-a", tag, "-m", f"Release {tag}"],
        check=True,
    )
    print(f"✓ Created annotated tag {tag}")
    print(f"  Push with: git push origin {tag}")


if __name__ == "__main__":
    main()
