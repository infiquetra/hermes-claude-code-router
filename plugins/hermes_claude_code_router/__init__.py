"""hermes-claude-code-router — Hermes plugin that routes Discord text to Claude Code sessions.

``register(ctx)`` is the Hermes plugin entry point (see
infiquetra-hermes-plugins/docs/plugin-authoring.md). It wires the v1 human-relay
spine:

* the ``pre_gateway_dispatch`` hook (routing fast path — see :mod:`.router`),
* ``/cc list`` / ``connect`` / ``disconnect`` / ``switch`` slash commands, and
* a lazily-started outbound relay (:mod:`.outbound`) that delivers CC replies back
  to Discord once the gateway has been captured by the first hook event.

Redis is not contacted at load time: a missing ``REDIS_URL`` is reported clearly,
but the connection is deferred until a hook event captures the gateway (the relay)
or a command needs it (``/cc list``). The exact Hermes command-context and adapter
internals are confirmed against the live profile at the acceptance gate (KTD5).

See PROTOCOL.md (sibling file) for the Redis-streams wire format shared with the
companion redis-channel plugin.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from .outbound import OutboundRelay
from .redis_client import RouterRedis
from .registry_reader import list_live_sessions
from .router import (
    DEFAULT_ENDPOINT,
    get_captured_gateway,
    get_routing_state,
    handle_pre_gateway_dispatch,
)

logger = logging.getLogger(__name__)

__version__ = "0.1.0"

_REDIS_URL_ENV = "REDIS_URL"
_ENDPOINT_ENV = "CC_ROUTER_ENDPOINT"

# Module state set up at register() time.
_config: dict[str, Any] = {}
_redis: RouterRedis | None = None
_relay: OutboundRelay | None = None


def _get_redis() -> RouterRedis:
    """Lazily connect to Redis (cached). Monkeypatched in tests."""
    global _redis
    if _redis is None:
        _redis = RouterRedis.from_env()
    return _redis


def _maybe_start_relay() -> None:
    """Start the outbound relay once the gateway has been captured.

    Called from the hook wrapper after each event. The relay needs both the
    captured gateway (for sending) and a Redis connection; both are deferred to
    here so register() never blocks on Redis. Idempotent.
    """
    global _relay
    if get_captured_gateway() is None:
        return
    if _relay is None:
        try:
            redis = _get_redis()
        except Exception:  # noqa: BLE001 - degrade: routing-in still works, replies disabled
            logger.exception("outbound relay: Redis unavailable; CC replies disabled")
            return
        _relay = OutboundRelay(
            redis, get_routing_state().active_targets, get_captured_gateway
        )
    _relay.start()


def _hook(event: Any, gateway: Any | None = None, **kwargs: Any) -> dict[str, str] | None:
    """``pre_gateway_dispatch`` wrapper: route, then lazily start the relay."""
    result = handle_pre_gateway_dispatch(event, gateway, config=_config, **kwargs)
    _maybe_start_relay()
    return result


def _format_sessions(sessions: list[dict[str, Any]]) -> str:
    """Render the live-session list for ``/cc list``."""
    if not sessions:
        return "No live Claude Code sessions."
    lines = ["Live Claude Code sessions:"]
    for s in sessions:
        branch = s.get("git_branch") or "?"
        seen = s.get("last_seen_seconds")
        seen_str = "just now" if seen is None else f"{int(seen)}s ago"
        lines.append(
            f"- {s.get('session_name')} ({s.get('cwd_basename')} @ {branch}) — seen {seen_str}"
        )
    return "\n".join(lines)


def _cmd_list(*_args: Any, **_kwargs: Any) -> str:
    """``/cc list`` — surface live sessions from the presence registry."""
    return _format_sessions(list_live_sessions(_get_redis()))


def _cmd_connect(*_args: Any, **_kwargs: Any) -> str:
    """``/cc connect <name>`` — convenience over the natural-language matcher.

    The per-surface routing state is keyed by (user_id, endpoint, chat_id), which
    requires the command context's surface identity. That context shape is
    confirmed at the acceptance gate; until then the natural-language form
    ("connect to session <name>") handled by the hook is the supported path.
    """
    return "Use: connect to session <name> (slash-command context wiring lands at the acceptance gate)."


def _cmd_disconnect(*_args: Any, **_kwargs: Any) -> str:
    """``/cc disconnect`` — see :func:`_cmd_connect` on context wiring."""
    return "Use: disconnect (slash-command context wiring lands at the acceptance gate)."


def _cmd_switch(*_args: Any, **_kwargs: Any) -> str:
    """``/cc switch <name>`` — see :func:`_cmd_connect` on context wiring."""
    return "Use: switch to <name> (slash-command context wiring lands at the acceptance gate)."


def register(ctx: Any) -> None:
    """Entry point called by Hermes at plugin load time.

    Wires the routing hook, the slash commands, and the (deferred) outbound relay.
    Raises a clear error if ``REDIS_URL`` is unset — the router cannot function
    without a Redis endpoint, and failing fast at load beats a silent no-op.
    """
    if not os.environ.get(_REDIS_URL_ENV):
        raise RuntimeError(
            f"{_REDIS_URL_ENV} is unset; hermes-claude-code-router requires a Redis "
            f"endpoint (e.g. redis://host:6379/0). Set {_REDIS_URL_ENV} before loading."
        )

    _config.clear()
    _config["endpoint"] = os.environ.get(_ENDPOINT_ENV, DEFAULT_ENDPOINT)

    ctx.register_hook("pre_gateway_dispatch", _hook)
    ctx.register_command("/cc list", _cmd_list, "List live Claude Code sessions")
    ctx.register_command("/cc connect", _cmd_connect, "Route this conversation to a CC session")
    ctx.register_command("/cc disconnect", _cmd_disconnect, "Stop routing; hand back to the agent")
    ctx.register_command("/cc switch", _cmd_switch, "Switch the routing target to another session")

    logger.info(
        "hermes_claude_code_router v%s registered (endpoint=%s)",
        __version__,
        _config["endpoint"],
    )
