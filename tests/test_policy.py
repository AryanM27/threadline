import pytest
from automation.policy import Policy, PolicyEngine, PolicyDenied, redact


def _engine():
    return PolicyEngine(Policy(
        allowed_origins=[
            {"scheme": "https", "host": "automationexercise.com"},
            {"scheme": "https", "host": "www.automationexercise.com"},
            {"scheme": "http", "host": "127.0.0.1", "port": 8000, "dev_only": True},
        ],
        denied_route_patterns=["/payment*", "/order*"],
        allowed_actions=["navigate", "click", "fill", "select", "extract", "assert"],
    ))


def test_allowed_origin_passes():
    _engine().check_url("https://automationexercise.com/products")


def test_lookback_origin_requires_matching_port():
    _engine().check_url("http://127.0.0.1:8000/index.html")
    with pytest.raises(PolicyDenied):
        _engine().check_url("http://127.0.0.1:9999/index.html")


def test_substring_lookalike_host_denied():
    # The classic bug this guards: "automationexercise.com.evil.io" contains
    # the allowed host as a substring but is a different origin entirely.
    with pytest.raises(PolicyDenied):
        _engine().check_url("https://automationexercise.com.evil.io/products")


def test_scheme_downgrade_denied():
    with pytest.raises(PolicyDenied):
        _engine().check_url("http://automationexercise.com/products")


def test_offsite_redirect_destination_denied():
    with pytest.raises(PolicyDenied) as exc:
        _engine().check_url("https://ads.example.com/tracker")
    assert exc.value.code == "policy_origin_denied"


def test_denied_route_rejected_even_on_allowed_origin():
    with pytest.raises(PolicyDenied) as exc:
        _engine().check_url("https://automationexercise.com/payment/confirm")
    assert exc.value.code == "policy_route_denied"


def test_unknown_action_denied():
    with pytest.raises(PolicyDenied):
        _engine().check_action("execute_script")


def test_requires_human_risk_needs_intervention():
    assert _engine().needs_human("requires_human") is True
    assert _engine().needs_human("safe") is False


def test_redaction_is_recursive_and_covers_common_secret_keys():
    payload = {
        "password": "hunter2",
        "email": "a@b.com",
        "nested": [{"api_key": "sk-123", "product": "Blue Top"}],
    }
    out = redact(payload, sensitive_names={"email"})
    assert out["password"] == "[REDACTED]"
    assert out["email"] == "[REDACTED]"
    assert out["nested"][0]["api_key"] == "[REDACTED]"
    assert out["nested"][0]["product"] == "Blue Top"


def test_redaction_does_not_mutate_input():
    payload = {"password": "hunter2"}
    redact(payload, sensitive_names=set())
    assert payload["password"] == "hunter2"
