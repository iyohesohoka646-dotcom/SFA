"""Module entry: run with ``python -m research_lab.main``.

The relative import needs the enclosing ``research_lab`` package to be
importable, which is why the run supplies an explicit ``PYTHONPATH`` pointing
at this project's ``src`` directory. Nothing here is installed.
"""

from . import compute


def run():
    values = compute.build_dataset()
    score = compute.summarize(values)
    print(score)
    return score


if __name__ == "__main__":
    run()