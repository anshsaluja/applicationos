"""Regression checks for strict browser origin configuration."""

import pytest

from app.main import parse_cors_origins


@pytest.mark.parametrize(
    "value",
    [
        "http://example.com\\@attacker.example",
        "http://example.com:",
        "http://[::1]:",
        "http://exa\tmple.com",
        "http://example.com\nattacker.example",
        "https://example.com/path",
        "https://user@example.com",
        "https://*.example.com",
        "http://exa mple.com",
        "http://example.com?",
        "http://example.com#",
        "http://exa\u00a0mple.com",
        "https://bücher.example",
        "https://example.com\u200b",
    ],
)
def test_reject_ambiguous_or_unsafe_origins(value: str) -> None:
    with pytest.raises(ValueError, match="CORS_ALLOWED_ORIGINS"):
        parse_cors_origins(value)


def test_accept_explicit_origins_and_deduplicate() -> None:
    assert parse_cors_origins(
        "http://localhost:3000, https://example.com:443, http://localhost:3000"
    ) == ["http://localhost:3000", "https://example.com:443"]


def test_accept_punycode_idn_origin() -> None:
    assert parse_cors_origins("https://xn--bcher-kva.example") == [
        "https://xn--bcher-kva.example"
    ]


def test_accept_ipv6_with_valid_port() -> None:
    assert parse_cors_origins("http://[::1]:3000") == ["http://[::1]:3000"]
