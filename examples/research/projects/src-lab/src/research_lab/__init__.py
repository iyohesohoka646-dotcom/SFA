"""Import-marker package for the src-layout example.

Importing this package runs this initializer exactly once. Python caches the
module object in ``sys.modules``, so a second ``import research_lab`` does not
re-run it and no marker file is written to disk. ``INITIALIZATIONS`` is that
observable, side-effect-free count.
"""

INITIALIZATIONS = 0
INITIALIZATIONS += 1

__all__ = ["compute", "main"]