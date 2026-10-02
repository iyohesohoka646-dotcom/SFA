import time

from contract_driven_ai_flow.research.agent.privacy import clean_text


def test_plain_large_context_redaction_is_bounded():
    text = 'a' * 18000
    started = time.perf_counter()
    assert clean_text(text, 32768) == text
    assert time.perf_counter() - started < .5


def test_credential_assignment_names_and_normal_strings_are_handled():
    text = 'normal = "keep"\nservice_access_token = "hide-me"\napi_key = "hide-this"\npassword: xyz\n'
    result = clean_text(text, 32768)
    assert '"keep"' in result and 'hide-me' not in result and 'hide-this' not in result and 'xyz' not in result
