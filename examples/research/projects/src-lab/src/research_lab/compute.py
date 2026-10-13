"""Dependency-free dataset and integer summary for the src-layout example.

``build_dataset`` and ``summarize`` each use a local ``X``; the two bindings sit
in separate function scopes, so they stay distinct when a project run traces
both files.
"""

import random

SEED = 20261013
SIZE = 12


def build_dataset(seed=SEED, size=SIZE):
    """Return ``size`` reproducible integers from a private Random instance."""
    rng = random.Random(seed)
    X = [rng.randrange(10, 100) for _ in range(size)]
    return X


def summarize(values, fail=False):
    """Fold ``values`` into an integer mean, or raise a real ``ValueError``."""
    X = [int(value) for value in values]
    if not X:
        raise ValueError("dataset must not be empty")
    if fail:
        raise ValueError("requested failure inside compute.summarize")
    total = 0
    for value in X:
        total += value
    score = total // len(X)
    return score