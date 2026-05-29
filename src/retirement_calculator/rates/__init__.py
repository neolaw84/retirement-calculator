"""Rate functions for the retirement calculator."""

from __future__ import annotations

import abc
import numpy as np


class RateFunction(abc.ABC):
    """Abstract base class for rate functions used in the simulator."""

    @abc.abstractmethod
    def sample(self, rng: np.random.Generator | None = None) -> float:
        """Return a rate sample (e.g., annual growth rate as a decimal, e.g. 0.07)."""

    def __call__(self, rng: np.random.Generator | None = None) -> float:
        return self.sample(rng)


class ConstantRate(RateFunction):
    """Always returns the same rate."""

    def __init__(self, rate: float) -> None:
        self.rate = rate

    def sample(self, rng: np.random.Generator | None = None) -> float:
        return self.rate

    def __repr__(self) -> str:
        return f"ConstantRate({self.rate:.4f})"


class NormalRate(RateFunction):
    """Draws a rate from a normal distribution each call.

    Parameters
    ----------
    mean : float
        Mean annual rate (e.g. 0.07 for 7%).
    std : float
        Standard deviation of the annual rate.
    floor : float | None
        Optional lower bound; samples below this are clipped.  Defaults to None.
    """

    def __init__(self, mean: float, std: float, floor: float | None = None) -> None:
        self.mean = mean
        self.std = std
        self.floor = floor

    def sample(self, rng: np.random.Generator | None = None) -> float:
        generator = rng if rng is not None else np.random.default_rng()
        value = generator.normal(self.mean, self.std)
        if self.floor is not None:
            value = max(self.floor, value)
        return value

    def __repr__(self) -> str:
        return f"NormalRate(mean={self.mean:.4f}, std={self.std:.4f})"


class HistoricalRate(RateFunction):
    """Samples from a provided list of historical returns.

    Parameters
    ----------
    returns : list[float]
        Historical annual returns (nominal or real).
    """

    def __init__(self, returns: list[float]) -> None:
        self.returns = returns

    def sample(self, rng: np.random.Generator | None = None) -> float:
        generator = rng if rng is not None else np.random.default_rng()
        return float(generator.choice(self.returns))

    def __repr__(self) -> str:
        return f"HistoricalRate(n={len(self.returns)})"
