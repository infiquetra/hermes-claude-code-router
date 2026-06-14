"""Presence-aware reader over the ``cc-sessions:registry`` hash.

The CC plugin (``redis-channel``) registers static session metadata as a
field-per-session in the ``cc-sessions:registry`` hash and refreshes a
short-lived heartbeat key (``cc-sessions:hb:<session_name>``, ``EX 60``) every
10s. Per PROTOCOL.md ("Presence") the registry entry is **never** eagerly
removed — it's lazily GC'd — so a router MUST treat ``EXISTS
cc-sessions:hb:<session_name>`` as the source of truth for liveness and filter
the registry through it.

This module does exactly that:

1. ``HGETALL cc-sessions:registry`` (via the U1 :class:`RouterRedis`).
2. Validate each field value as a :class:`RegistryEntry`. Stale/malformed JSON
   is logged and skipped — never raised — so one bad entry can't take down the
   list ("lazy-ignore").
3. Keep only entries whose heartbeat key currently ``EXISTS``.
4. Project each survivor into a compact, UI-friendly dict.

It is read-only: it never writes Redis and holds no in-memory state.
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from .protocol import RegistryEntry

if TYPE_CHECKING:
    from .redis_client import RouterRedis

logger = logging.getLogger(__name__)

# Hash holding static per-session metadata (field == session_name).
REGISTRY_KEY = "cc-sessions:registry"
# Heartbeat key prefix; the suffix is the session_name. Presence == EXISTS.
HEARTBEAT_PREFIX = "cc-sessions:hb:"
# The CC plugin sets the hb key with ``EX 60`` (PROTOCOL.md "Heartbeat"); the
# remaining TTL lets us derive how long ago the last beat landed.
HEARTBEAT_TTL_SECONDS = 60


def heartbeat_key(session_name: str) -> str:
    """Return the heartbeat key for ``session_name``."""
    return f"{HEARTBEAT_PREFIX}{session_name}"


def _last_seen_seconds(redis: RouterRedis, session_name: str) -> float | None:
    """Seconds since the last heartbeat beat, derived from the hb key's TTL.

    The CC plugin refreshes the hb key with ``EX 60``, so ``60 - TTL`` is how
    long ago the beat was written, clamped to ``>= 0``. Returns ``None`` when
    the TTL is unavailable (key missing, or set without an expiry — TTL ``-2`` /
    ``-1``), since "age" can't be computed in that case.
    """
    ttl = int(redis.client.ttl(heartbeat_key(session_name)))
    if ttl < 0:
        return None
    return max(0.0, float(HEARTBEAT_TTL_SECONDS - ttl))


def _parse_entry(session_name: str, raw_value: Any) -> RegistryEntry | None:
    """Validate one registry field value into a :class:`RegistryEntry`.

    Returns ``None`` (and logs at WARNING) on malformed JSON or a payload that
    fails schema validation — the caller skips it rather than crashing the list.
    """
    try:
        payload = json.loads(raw_value)
    except (TypeError, json.JSONDecodeError):
        logger.warning(
            "registry entry %r has malformed JSON; skipping", session_name
        )
        return None
    try:
        return RegistryEntry.model_validate(payload)
    except ValidationError:
        logger.warning(
            "registry entry %r failed RegistryEntry validation; skipping",
            session_name,
        )
        return None


def _project(entry: RegistryEntry, last_seen_seconds: float | None) -> dict[str, Any]:
    """Project a validated entry into the compact live-session dict."""
    return {
        "session_name": entry.session_name,
        "cwd_basename": os.path.basename(entry.cwd.rstrip("/")) or entry.cwd,
        "git_branch": entry.git_branch,
        "started_at": entry.started_at,
        "last_seen_seconds": last_seen_seconds,
    }


def list_live_sessions(redis: RouterRedis) -> list[dict[str, Any]]:
    """Return the live sessions in ``cc-sessions:registry``.

    "Live" == the entry validates AND its heartbeat key currently exists.
    Malformed / stale entries are logged and skipped. Each returned dict has:
    ``session_name``, ``cwd_basename``, ``git_branch``, ``started_at``,
    ``last_seen_seconds``. Returns ``[]`` for an empty registry.
    """
    registry = redis.hgetall(REGISTRY_KEY)
    live: list[dict[str, Any]] = []
    for session_name, raw_value in registry.items():
        entry = _parse_entry(session_name, raw_value)
        if entry is None:
            continue
        if not redis.exists(heartbeat_key(entry.session_name)):
            # Registry entry without a heartbeat == stale presence; lazy-ignore.
            continue
        live.append(_project(entry, _last_seen_seconds(redis, entry.session_name)))
    return live
