"""Authored script entry for the flat-lab example.

The project's one saved entry is this file, run as a script. It imports its
siblings (``prepare``, ``compute``, ``checks``) through the script directory
that the interpreter puts on ``sys.path``; every sibling is a real file, not a
copy. The final module-level ``score`` is numeric and printed as ``str(score)``
so the native stdout and the observed snapshot agree byte for byte.
"""

import argparse

import checks
import compute
import prepare


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Deterministic flat-lab pipeline")
    parser.add_argument(
        "--fail",
        action="store_true",
        help="raise a real ValueError inside compute after the dataset is captured",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    values = prepare.build_dataset()
    score = compute.summarize(values, fail=args.fail)
    checks.verify(score)
    print(score)
    return score


if __name__ == "__main__":
    main()