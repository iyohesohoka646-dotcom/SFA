"""Fixture listeners require the private session created by Playwright."""
import os
import re


def fixture_session():
    token = os.environ.get("CDAF_BROWSER_TEST_SESSION", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", token):
        raise ValueError("Set a private per-run CDAF_BROWSER_TEST_SESSION before starting a fixture listener")
    return token
