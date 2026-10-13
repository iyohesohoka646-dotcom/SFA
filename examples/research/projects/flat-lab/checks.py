"""Small numeric verification with no external dependency."""


def verify(score, minimum=0, maximum=100):
    """Return True for an in-range integer score, otherwise raise ValueError."""
    ok = isinstance(score, int) and minimum <= score <= maximum
    if not ok:
        raise ValueError("score out of range: " + repr(score))
    return ok