"""retirement-calculator - Retirement Calculator for Australian Tax Resident to FIRE."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("retirement-calculator")
except PackageNotFoundError:  # package not installed (e.g. running from source)
    __version__ = "unknown"

__author__ = "Edward L"
__email__ = "neolaw@gmail.com"
