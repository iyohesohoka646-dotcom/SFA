"""Keep the sfa executable for one major version, with explicit legacy access."""
import sys


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "legacy":
        from sfa.cli import app
        sys.argv.pop(1)
        app()
    else:
        from .cli import app
        app()
