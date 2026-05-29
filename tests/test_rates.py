import pytest
import numpy as np
from retirement_calculator.rates import ConstantRate, NormalRate

def test_constant_rate():
    rate = ConstantRate(0.05)
    assert rate.sample() == 0.05
    assert rate() == 0.05
    assert "0.0500" in repr(rate)

def test_normal_rate_basic():
    rate = NormalRate(mean=0.07, std=0.02)
    rng = np.random.default_rng(42)
    samples = [rate.sample(rng) for _ in range(1000)]
    assert 0.06 < np.mean(samples) < 0.08
    assert 0.015 < np.std(samples) < 0.025

def test_normal_rate_floor():
    rate = NormalRate(mean=0.05, std=0.2, floor=0.0)
    rng = np.random.default_rng(42)
    samples = [rate.sample(rng) for _ in range(1000)]
    assert min(samples) >= 0.0
