"""Slash/regex intent matchers for router-control phrases.

The router runs operator text through these matchers on the fast path (before
any LLM fallback) to resolve control intents — connect/disconnect/list/switch a
routing target, or toggle routing mode on/off.

Patterns are read from plugin config shaped like the master-plan host_vars:
``connect_patterns`` / ``disconnect_patterns`` / ``list_patterns`` /
``switch_patterns`` (each a list of regex strings), and ``mode_phrases``
(a dict with ``start`` / ``stop`` phrase lists). Any unset key falls back to a
built-in default, so a bare ``{}`` config still matches the canonical phrases.

A pattern that targets a session uses a named capture group ``name`` (e.g.
``(?P<name>\\S+)``). The captured name is validated against
:data:`SESSION_NAME_RE`; a structurally-matching phrase carrying an invalid
session name does NOT match (the matcher returns ``None``), so junk never
reaches the routing state.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# Valid Claude Code session names: lowercase alnum start, then alnum/_/- up to
# 64 chars total. Mirrors the registry naming convention in PROTOCOL.md.
SESSION_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def is_valid_session_name(name: str) -> bool:
    """Return True if ``name`` is a structurally valid session name."""
    return SESSION_NAME_RE.match(name) is not None


class Intent(StrEnum):
    """Router-control intents resolvable from a single operator phrase."""

    CONNECT = "connect"
    DISCONNECT = "disconnect"
    LIST = "list"
    SWITCH = "switch"
    MODE_START = "mode_start"
    MODE_STOP = "mode_stop"


@dataclass(frozen=True)
class MatchResult:
    """A resolved control intent and, where relevant, its target session name."""

    intent: Intent
    name: str | None = None


# ─── Built-in defaults ───────────────────────────────────────────────────────
# All patterns are case-insensitive (compiled with re.IGNORECASE); the source
# strings stay lowercase for readability. Session-bearing patterns carry a
# ``(?P<name>...)`` group.

_DEFAULT_CONNECT_PATTERNS = [
    r"connect to (?:session|cc)\s+(?P<name>\S+)",
    r"/cc connect\s+(?P<name>\S+)",
]

_DEFAULT_SWITCH_PATTERNS = [
    r"switch to\s+(?P<name>\S+)",
    r"/cc switch\s+(?P<name>\S+)",
]

_DEFAULT_DISCONNECT_PATTERNS = [
    r"disconnect(?:\s+(?:from\s+)?(?:session|cc))?",
    r"/cc disconnect",
]

_DEFAULT_LIST_PATTERNS = [
    r"list (?:cc |claude )?sessions?",
    r"/cc list",
]

_DEFAULT_MODE_PHRASES: dict[str, list[str]] = {
    "start": ["start coding session", "claude take over"],
    "stop": ["end coding session", "mimir take over", "stop routing"],
}

# Order matters: more-specific session-bearing intents (connect, switch) are
# tried before bare-verb intents so "switch to foo" resolves to SWITCH, not a
# looser disconnect/list pattern.
_INTENT_CONFIG_KEYS: list[tuple[Intent, str, list[str]]] = [
    (Intent.CONNECT, "connect_patterns", _DEFAULT_CONNECT_PATTERNS),
    (Intent.SWITCH, "switch_patterns", _DEFAULT_SWITCH_PATTERNS),
    (Intent.LIST, "list_patterns", _DEFAULT_LIST_PATTERNS),
    (Intent.DISCONNECT, "disconnect_patterns", _DEFAULT_DISCONNECT_PATTERNS),
]


class Matcher:
    """Compiled control-phrase matcher built from a plugin config dict.

    Construct once per endpoint config; :meth:`match` is then cheap and stateless.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self._compiled: list[tuple[Intent, list[re.Pattern[str]]]] = []
        for intent, key, default in _INTENT_CONFIG_KEYS:
            raw = cfg.get(key, default)
            self._compiled.append((intent, [_compile(p) for p in raw]))

        mode = cfg.get("mode_phrases", _DEFAULT_MODE_PHRASES) or {}
        self._mode_start = [_compile_phrase(p) for p in mode.get("start", [])]
        self._mode_stop = [_compile_phrase(p) for p in mode.get("stop", [])]

    def match(self, text: str) -> MatchResult | None:
        """Resolve ``text`` to a control intent, or ``None`` if nothing matches.

        A session-bearing pattern whose captured ``name`` fails validation is
        skipped, so an invalid session name yields ``None`` rather than a bad
        target.
        """
        stripped = text.strip()
        if not stripped:
            return None

        # Mode toggles first — they are exact-ish phrases, not session-bearing.
        for pat in self._mode_start:
            if pat.search(stripped):
                return MatchResult(Intent.MODE_START)
        for pat in self._mode_stop:
            if pat.search(stripped):
                return MatchResult(Intent.MODE_STOP)

        for intent, patterns in self._compiled:
            for pat in patterns:
                m = pat.search(stripped)
                if m is None:
                    continue
                name = _extract_name(m)
                if name is not None and not is_valid_session_name(name):
                    # Structural match but the session name is junk — reject.
                    continue
                return MatchResult(intent, name)

        return None


def _compile(pattern: str) -> re.Pattern[str]:
    """Compile a config-supplied regex case-insensitively.

    Inline ``(?i)`` flags from the host_vars examples are tolerated by Python's
    ``re``; we add :data:`re.IGNORECASE` regardless so plain patterns are also
    case-insensitive.
    """
    return re.compile(pattern, re.IGNORECASE)


def _compile_phrase(phrase: str) -> re.Pattern[str]:
    """Compile a literal mode phrase as a whole-token substring match."""
    return re.compile(rf"\b{re.escape(phrase.strip())}\b", re.IGNORECASE)


def _extract_name(m: re.Match[str]) -> str | None:
    """Return the ``name`` capture group if the pattern defined one."""
    if "name" not in m.re.groupindex:
        return None
    captured = m.group("name")
    if captured is None:
        return None
    return captured.strip()
