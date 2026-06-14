"""Router hook for ``pre_gateway_dispatch`` — the human-relay spine's fast path.

This is the single integration point with Hermes. Voice and text both arrive
through ``pre_gateway_dispatch`` (there is no separate voice hook — see
LEARNINGS#voice-via-pre-gateway-dispatch); the handler distinguishes them via
``event.message_type``.

Decision order (LEARNINGS#hermes-pre-gateway-dispatch-contract):

1. **Control match first.** Run the operator text through :class:`~.matchers.Matcher`.
   A state-changing match (connect/switch/disconnect/mode toggle) mutates the
   in-memory :class:`~.mode_state.RoutingState` and returns ``{"action":"skip"}``
   so Mimir's LLM does not also respond. A non-state-changing control match
   (``list``) is also consumed (skip) — the router owns that surface.
2. **Route if targeted.** Otherwise, if a routing target is set for this surface
   AND the message carries text, build a validated :class:`~.protocol.Inbound`,
   XADD it to ``cc-sessions:<target>:inbound`` via the U1 Redis client, and skip.
3. **Pass through.** Otherwise return ``None`` — Mimir's LLM handles the message.

The ``gateway`` reference is captured into module state on first call: it is only
reachable from the hook event, not at ``register()`` time, and downstream
out-of-band sends (the XREADGROUP delivery loop) need it
(LEARNINGS#outbound-text-via-discord-py).

A payload that fails ``Inbound`` validation is logged and dropped; the hook still
returns cleanly (skip) so a malformed event never crashes the gateway and Mimir
does not double-respond to a message the router already consumed.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from .matchers import Intent, Matcher, MatchResult
from .mode_state import RoutingState
from .protocol import Inbound, SourceType
from .redis_client import RouterRedis

logger = logging.getLogger(__name__)

# Default endpoint name when config does not specify one. Mimir is the reference
# deployment (CLAUDE.md "Where Hermes runs").
DEFAULT_ENDPOINT = "mimir"
ROUTER_NAME = "hermes-claude-code-router"

# ``message_type`` → protocol ``source`` mapping. Voice transcripts arrive as
# "voice"; Discord text surfaces vary ("text", "mention", "dm", "thread") — see
# the build narrative. Anything unrecognized defaults to "dm" (dm-style
# formatting is the safe fallback per the channel protocol).
_SOURCE_BY_MESSAGE_TYPE: dict[str, SourceType] = {
    "voice": "voice",
    "dm": "dm",
    "text": "dm",
    "channel": "channel",
    "mention": "channel",
    "thread": "thread",
}

# ── Module-level captured state ──────────────────────────────────────────────
# The gateway is captured on first hook invocation (only reachable from the
# event, not at register time). The RoutingState is a process-lifetime singleton
# (KTD: routing state lives in plugin memory, no persistence).
_gateway: Any | None = None
_routing_state = RoutingState()


def get_captured_gateway() -> Any | None:
    """Return the gateway captured from the first hook event, or ``None``."""
    return _gateway


def get_routing_state() -> RoutingState:
    """Return the process-lifetime in-memory routing state."""
    return _routing_state


def _source_from_message_type(message_type: Any) -> SourceType:
    """Map an event ``message_type`` onto a protocol ``source``."""
    return _SOURCE_BY_MESSAGE_TYPE.get(str(message_type).lower(), "dm")


def _chat_id_from_event(event: Any) -> str | None:
    """Derive the opaque ``chat_id`` from the event's surface id.

    The channel/voice-channel id is the conversation surface. It lives on
    ``event.source.channel_id`` and/or top-level ``event.channel_id`` (the
    gateway emits both shapes — LEARNINGS#hermes-pre-gateway-dispatch-contract).
    Returns ``None`` if neither is present, so the caller can pass through.
    """
    source = getattr(event, "source", None)
    chat_id = getattr(source, "channel_id", None)
    if chat_id is None:
        chat_id = getattr(event, "channel_id", None)
    return None if chat_id is None else str(chat_id)


def _user_id_from_event(event: Any) -> str | None:
    """Derive the opaque user id from ``event.source.user_id`` (or ``.author_id``)."""
    source = getattr(event, "source", None)
    user_id = getattr(source, "user_id", None)
    if user_id is None:
        user_id = getattr(source, "author_id", None)
    return None if user_id is None else str(user_id)


def _username_from_event(event: Any, user_id: str) -> str:
    """Best-effort display name; falls back to the opaque user id."""
    source = getattr(event, "source", None)
    for attr in ("username", "display_name", "name"):
        value = getattr(source, attr, None) or getattr(event, attr, None)
        if value:
            return str(value)
    return user_id


def _apply_control_intent(
    result: MatchResult,
    *,
    user_id: str,
    endpoint: str,
    chat_id: str,
    state: RoutingState,
) -> str:
    """Mutate routing state for a control intent; return a skip-reason string.

    ``list`` carries no state mutation — the router still consumes it (the
    operator-facing listing is rendered elsewhere), so it returns a reason
    without touching state.
    """
    intent = result.intent
    if intent in (Intent.CONNECT, Intent.SWITCH) and result.name:
        state.set_target(user_id, endpoint, chat_id, result.name)
        return f"routing target set to {result.name}"
    if intent is Intent.DISCONNECT:
        state.clear_target(user_id, endpoint, chat_id)
        return "routing target cleared"
    if intent is Intent.MODE_START:
        state.set_routing(user_id, endpoint, chat_id, enabled=True)
        return "routing mode started"
    if intent is Intent.MODE_STOP:
        state.set_routing(user_id, endpoint, chat_id, enabled=False)
        return "routing mode stopped"
    # LIST (or a CONNECT/SWITCH with no captured name): consume without mutating.
    return f"control intent {intent.value} consumed"


def _skip(reason: str) -> dict[str, str]:
    """Build the standard skip return value (suppresses Mimir's LLM)."""
    return {"action": "skip", "reason": reason}


def handle_pre_gateway_dispatch(
    event: Any,
    gateway: Any | None = None,
    *,
    redis: RouterRedis | None = None,
    matcher: Matcher | None = None,
    state: RoutingState | None = None,
    config: dict[str, Any] | None = None,
    **_kw: Any,
) -> dict[str, str] | None:
    """``pre_gateway_dispatch`` handler — the router's fast-path decision.

    Returns ``{"action":"skip", "reason":...}`` when the router consumes the
    message (control match or routed to a CC session), or ``None`` to let
    Mimir's LLM respond. Never raises: a malformed event or a payload that fails
    ``Inbound`` validation is logged and the hook returns cleanly.

    ``redis``/``matcher``/``state``/``config`` are injectable for tests; in
    production they default to the module singletons / lazily-built collaborators.
    """
    global _gateway
    if gateway is not None and _gateway is None:
        _gateway = gateway

    cfg = config or {}
    endpoint = str(cfg.get("endpoint", DEFAULT_ENDPOINT))
    active_state = state if state is not None else _routing_state
    active_matcher = matcher if matcher is not None else Matcher(cfg)

    text = getattr(event, "text", None)
    user_id = _user_id_from_event(event)
    chat_id = _chat_id_from_event(event)

    # No usable surface identity → cannot route or scope control state. Pass through.
    if user_id is None or chat_id is None:
        logger.debug("pre_gateway_dispatch: missing user_id/chat_id; passing through")
        return None

    # ── 1. Control match (fast path, no LLM) ────────────────────────────────
    if isinstance(text, str) and text.strip():
        match = active_matcher.match(text)
        if match is not None:
            reason = _apply_control_intent(
                match,
                user_id=user_id,
                endpoint=endpoint,
                chat_id=chat_id,
                state=active_state,
            )
            logger.info("router matched %s (chat=%s): %s", match.intent.value, chat_id, reason)
            return _skip(reason)

    # ── 2. Route to a CC session if one is targeted ─────────────────────────
    target = active_state.get_target(user_id, endpoint, chat_id)
    if target is None:
        logger.debug("router passed through (no target, chat=%s)", chat_id)
        return None

    if not isinstance(text, str) or not text.strip():
        # Targeted surface but nothing routable (e.g. attachment-only). Pass through.
        logger.debug("router has target %s but no text; passing through", target)
        return None

    client = redis if redis is not None else RouterRedis.from_env()
    stream = f"cc-sessions:{target}:inbound"
    source = _source_from_message_type(getattr(event, "message_type", None))
    username = _username_from_event(event, user_id)
    confidence = getattr(event, "confidence", None)

    try:
        inbound = Inbound(
            router=ROUTER_NAME,
            endpoint=endpoint,
            source=source,
            chat_id=chat_id,
            user_id=user_id,
            username=username,
            text=text,
            confidence=confidence if isinstance(confidence, (int, float)) else None,
            ts=time.time(),
            metadata={},
        )
    except Exception:  # noqa: BLE001 - any validation failure is a drop, not a crash
        logger.exception(
            "router dropped malformed inbound (target=%s, chat=%s): validation failed",
            target,
            chat_id,
        )
        return _skip("inbound validation failed; dropped")

    msg_id = client.xadd_model(stream, inbound)
    logger.info("router routed→%s (chat=%s, msg_id=%s)", target, chat_id, msg_id)
    return _skip(f"routed to {target}")
