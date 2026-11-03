"""Named calculation for the flat-lab example: one loop, one branch.

``summarize`` reuses the name ``X`` inside its own function scope. That is a
different lexical binding from ``prepare.build_dataset``'s ``X``; observers keep
them as separate snapshots because Python keeps them as separate locals.
"""


def summarize(values, fail=False):
    """Fold ``values`` into an integer mean, or raise a real ``ValueError``."""
    X = [int(value) for value in values]
    if not X:
        raise ValueError("dataset must not be empty")
    if fail:
        # A genuine error raised *after* ``X`` was captured, so a failing run
        # still publishes the compute.py frame it reached.
        raise ValueError("requested failure inside compute.summarize")
    total = 0
    for value in X:
        total += value
    score = total // len(X)
    if score < 0:
        score = 0
    return score