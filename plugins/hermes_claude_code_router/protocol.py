"""Pydantic models for the redis-channel ↔ router protocol.

See PROTOCOL.md (sibling file) for the canonical specification. These models
are the enforcement layer: every inbound payload from Redis is validated
against them before processing; every outbound payload is serialized through
them. Schema mismatches fail loud, not silent.

This file is kept verbatim in sync with `redis-channel/server/protocol.py` in
`infiquetra/infiquetra-claude-plugins`. Any change to the protocol requires
synchronized PRs in both repos.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PROTOCOL_VERSION = 1

# Bash invocations matching any of these patterns are flagged destructive.
# Conservative on purpose; false positives just route through echo-confirm.
_DESTRUCTIVE_BASH_PATTERNS = [
    re.compile(r"\brm\s+(-[a-zA-Z]*r|--recursive)"),
    re.compile(r"\brm\s+-[a-zA-Z]*f"),
    re.compile(r"\bgit\s+push\s+.*--force"),
    re.compile(r"\bgit\s+push\s+.*-f\b"),
    re.compile(r"\bgit\s+reset\s+--hard"),
    re.compile(r"\bgit\s+clean\s+-[a-zA-Z]*f"),
    re.compile(r"\bgit\s+branch\s+-D\b"),
    re.compile(r"\bDROP\s+(TABLE|DATABASE|SCHEMA)\b", re.IGNORECASE),
    re.compile(r"\bTRUNCATE\s+TABLE\b", re.IGNORECASE),
    re.compile(r"\bDELETE\s+FROM\b", re.IGNORECASE),
    re.compile(r"\bdd\s+.*of=/dev/"),
    re.compile(r":\(\)\s*\{"),  # fork bomb
]

_ALWAYS_DESTRUCTIVE_TOOLS = {"Write", "Edit", "NotebookEdit"}


def is_destructive(tool_name: str, input_preview: str) -> bool:
    """Classify a tool invocation as destructive.

    Used by the CC plugin when constructing PermissionRequest payloads. The
    router uses this signal to decide whether to apply the echo-confirm
    safety net.
    """
    if tool_name in _ALWAYS_DESTRUCTIVE_TOOLS:
        return True
    if tool_name == "Bash":
        return any(p.search(input_preview) for p in _DESTRUCTIVE_BASH_PATTERNS)
    return False


class _Versioned(BaseModel):
    """Base for all protocol payloads."""

    model_config = ConfigDict(extra="allow")  # forward-compat: ignore unknown fields
    v: int = Field(default=PROTOCOL_VERSION)


# ─── Registry ────────────────────────────────────────────────────────────────


class RegistryEntry(_Versioned):
    """Static session metadata stored as a field in cc-sessions:registry."""

    session_name: str
    host: str
    cwd: str
    git_branch: str | None = None
    pid: int
    started_at: float
    capabilities: list[str] = Field(default_factory=list)


# ─── Inbound (router → CC) ───────────────────────────────────────────────────


SourceType = Literal["voice", "dm", "channel", "thread"]


class Inbound(_Versioned):
    router: str
    endpoint: str
    source: SourceType
    chat_id: str
    user_id: str
    username: str
    text: str
    confidence: float | None = None
    ts: float
    metadata: dict = Field(default_factory=dict)


# ─── Outbound (CC → router) ──────────────────────────────────────────────────


class Outbound(_Versioned):
    session_name: str
    endpoint: str
    chat_id: str
    text: str
    voice: bool = False
    in_reply_to: str | None = None
    ts: float


# ─── Permission relay ────────────────────────────────────────────────────────


class PermissionRequest(_Versioned):
    session_name: str
    endpoint: str
    request_id: str
    tool_name: str
    input_preview: str
    description: str | None = None
    destructive: bool
    originating_chat_id: str
    ts: float


Verdict = Literal["allow", "deny"]
VerdictSource = Literal["voice", "dm", "channel", "thread", "timeout"]
EchoOutcome = Literal["passed", "cancelled", "not_required"]


class PermissionVerdict(_Versioned):
    session_name: str
    endpoint: str
    request_id: str
    verdict: Verdict
    source: VerdictSource
    voice_confidence: float | None = None
    echo_confirm_outcome: EchoOutcome = "not_required"
    ts: float


# ─── Lifecycle events (pub/sub) ──────────────────────────────────────────────


EventType = Literal[
    "registered",
    "unregistered",
    "mode_change",
    "routing_target_changed",
    "presence_ping",
]


class LifecycleEvent(_Versioned):
    type: EventType
    session_name: str | None = None
    endpoint: str | None = None
    payload: dict = Field(default_factory=dict)
    ts: float
