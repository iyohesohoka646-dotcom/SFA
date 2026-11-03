"""Deterministic, dependency-free dataset preparation.

Everything here is one private ``random.Random(seed)`` instance in memory: no
clock, no global RNG state and no files written. ``X`` is deliberately reused
as a name in a second file (see ``compute.summarize``); each ``X`` lives in its
own lexical scope, so the two bindings never collide.
"""

import random

SEED = 20261013
SIZE = 12


def build_dataset(seed=SEED, size=SIZE):
    """Return ``size`` reproducible integers drawn from an isolated RNG."""
    rng = random.Random(seed)
    X = [rng.randrange(10, 100) for _ in range(size)]
    return X