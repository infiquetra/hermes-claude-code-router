"""Tests for the router-control phrase matchers.

The matcher resolves operator text to a control intent on the fast path (no
LLM). These cover the canonical phrases, non-matches, case-insensitivity,
config-overridden patterns, and rejection of structurally-matching phrases that
carry an invalid session name.
"""

from __future__ import annotations

import pytest

from hermes_claude_code_router.matchers import (
    SESSION_NAME_RE,
    Intent,
    Matcher,
    is_valid_session_name,
)


@pytest.fixture
def matcher() -> Matcher:
    """A matcher built from defaults (empty config)."""
    return Matcher({})


# ─── Canonical phrases ───────────────────────────────────────────────────────


def test_connect_with_session_name(matcher: Matcher) -> None:
    result = matcher.match("connect to session foo")
    assert result is not None
    assert result.intent is Intent.CONNECT
    assert result.name == "foo"


def test_slash_cc_list(matcher: Matcher) -> None:
    result = matcher.match("/cc list")
    assert result is not None
    assert result.intent is Intent.LIST
    assert result.name is None


def test_switch_with_session_name(matcher: Matcher) -> None:
    result = matcher.match("switch to bar")
    assert result is not None
    assert result.intent is Intent.SWITCH
    assert result.name == "bar"


def test_disconnect(matcher: Matcher) -> None:
    result = matcher.match("disconnect")
    assert result is not None
    assert result.intent is Intent.DISCONNECT
    assert result.name is None


def test_connect_cc_alias(matcher: Matcher) -> None:
    result = matcher.match("connect to cc my-session_1")
    assert result is not None
    assert result.intent is Intent.CONNECT
    assert result.name == "my-session_1"


def test_slash_cc_connect(matcher: Matcher) -> None:
    result = matcher.match("/cc connect foo")
    assert result is not None
    assert result.intent is Intent.CONNECT
    assert result.name == "foo"


# ─── Mode toggles ────────────────────────────────────────────────────────────


def test_mode_start_phrase(matcher: Matcher) -> None:
    result = matcher.match("start coding session")
    assert result is not None
    assert result.intent is Intent.MODE_START


def test_mode_stop_phrase(matcher: Matcher) -> None:
    result = matcher.match("stop routing")
    assert result is not None
    assert result.intent is Intent.MODE_STOP


# ─── Non-matches ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "what's the weather like today",
        "tell me a joke",
        "",
        "   ",
        "please summarize pr 117",
    ],
)
def test_non_matching_text_returns_none(matcher: Matcher, text: str) -> None:
    assert matcher.match(text) is None


# ─── Case-insensitivity ──────────────────────────────────────────────────────


def test_case_insensitive_connect(matcher: Matcher) -> None:
    result = matcher.match("CONNECT TO SESSION foo")
    assert result is not None
    assert result.intent is Intent.CONNECT
    assert result.name == "foo"


def test_case_insensitive_list(matcher: Matcher) -> None:
    result = matcher.match("/CC LIST")
    assert result is not None
    assert result.intent is Intent.LIST


def test_case_insensitive_mode_phrase(matcher: Matcher) -> None:
    result = matcher.match("Start Coding Session")
    assert result is not None
    assert result.intent is Intent.MODE_START


# ─── Config overrides ────────────────────────────────────────────────────────


def test_config_overridden_connect_pattern() -> None:
    matcher = Matcher(
        {"connect_patterns": [r"attach (?P<name>\S+)"]}
    )
    result = matcher.match("attach foo")
    assert result is not None
    assert result.intent is Intent.CONNECT
    assert result.name == "foo"


def test_config_override_replaces_default() -> None:
    # When connect_patterns is overridden, the built-in default no longer matches.
    matcher = Matcher({"connect_patterns": [r"attach (?P<name>\S+)"]})
    assert matcher.match("connect to session foo") is None


def test_config_overridden_mode_phrases() -> None:
    matcher = Matcher(
        {"mode_phrases": {"start": ["engage"], "stop": ["disengage"]}}
    )
    start = matcher.match("engage")
    stop = matcher.match("disengage")
    assert start is not None and start.intent is Intent.MODE_START
    assert stop is not None and stop.intent is Intent.MODE_STOP
    # Default mode phrase no longer fires under override.
    assert matcher.match("stop routing") is None


def test_inline_flag_pattern_compiles() -> None:
    # host_vars examples use inline (?i) flags; ensure they still work.
    matcher = Matcher({"list_patterns": [r"(?i)show sessions"]})
    result = matcher.match("SHOW SESSIONS")
    assert result is not None
    assert result.intent is Intent.LIST


# ─── Invalid session names ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad_name",
    [
        "FOO",  # uppercase
        "-leading-dash",  # cannot start with dash
        "_leading_underscore",  # cannot start with underscore
        "bad!char",  # punctuation
        "with.dot",  # dot not allowed
        "x" * 65,  # too long (>64)
    ],
)
def test_invalid_session_name_rejected(matcher: Matcher, bad_name: str) -> None:
    assert matcher.match(f"connect to session {bad_name}") is None


def test_multi_word_captures_first_token(matcher: Matcher) -> None:
    # \\S+ greedily takes the first whitespace-delimited token; "has" is a
    # valid session name, so the trailing words are ignored.
    result = matcher.match("connect to session has space")
    assert result is not None
    assert result.name == "has"


def test_valid_session_name_at_max_length(matcher: Matcher) -> None:
    name = "a" + "b" * 63  # exactly 64 chars
    result = matcher.match(f"connect to session {name}")
    assert result is not None
    assert result.name == name


def test_session_name_regex_helpers() -> None:
    assert is_valid_session_name("a") is True
    assert is_valid_session_name("a-b_c0") is True
    assert is_valid_session_name("0abc") is True
    assert is_valid_session_name("") is False
    assert is_valid_session_name("Abc") is False
    assert SESSION_NAME_RE.match("a" * 64) is not None
    assert SESSION_NAME_RE.match("a" * 65) is None
