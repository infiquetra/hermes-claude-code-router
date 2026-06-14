"""Tests for the ``pre_gateway_dispatch`` router hook.

Uses a simple mock event object (attributes mirroring the real gateway event:
``message_type``, ``text``, nested ``source`` with ``user_id`` / ``channel_id``)
and a fakeredis-backed :class:`RouterRedis`. No real Redis, Discord, or Hermes.

The router's decisions:
  * a control phrase ("connect to session foo") sets the target + returns skip;
  * a text message with a target set → XADD a VALID Inbound + returns skip;
  * no target → returns None (Mimir's LLM responds);
  * "disconnect" clears the target;
  * a payload that fails Inbound validation → logged + dropped, hook returns
    cleanly (skip, no exception).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import fakeredis
import pytest

from hermes_claude_code_router import router as router_mod
from hermes_claude_code_router.mode_state import RoutingState
from hermes_claude_code_router.protocol import Inbound
from hermes_claude_code_router.redis_client import RouterRedis

# ── Mock event ───────────────────────────────────────────────────────────────


@dataclass
class _MockSource:
    user_id: str = "u-42"
    channel_id: str = "chan-1"
    username: str = "jeff"


@dataclass
class _MockEvent:
    text: str | None = "hello"
    message_type: str = "text"
    source: _MockSource = field(default_factory=_MockSource)
    channel_id: str | None = None
    confidence: float | None = None


@dataclass
class _MockGateway:
    name: str = "gw"


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def fake_client() -> Any:
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def redis(fake_client: Any) -> RouterRedis:
    return RouterRedis(fake_client)


@pytest.fixture
def state() -> RoutingState:
    return RoutingState()


def _call(
    event: _MockEvent,
    *,
    redis: RouterRedis,
    state: RoutingState,
    gateway: Any | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, str] | None:
    """Invoke the hook with injected collaborators (default endpoint=mimir)."""
    return router_mod.handle_pre_gateway_dispatch(
        event,
        gateway,
        redis=redis,
        state=state,
        config=config if config is not None else {},
    )


def _read_inbound(redis: RouterRedis, target: str) -> list[Inbound]:
    stream = f"cc-sessions:{target}:inbound"
    return [model for _id, model in redis.read_models(stream, Inbound, block_ms=10)]


# ── Control match: connect sets the target ───────────────────────────────────


def test_connect_phrase_sets_target_and_skips(
    redis: RouterRedis, state: RoutingState
) -> None:
    event = _MockEvent(text="connect to session foo")
    result = _call(event, redis=redis, state=state)
    assert result == {"action": "skip", "reason": "routing target set to foo"}
    # Endpoint defaults to "mimir"; the surface now routes to "foo".
    assert state.get_target("u-42", "mimir", "chan-1") == "foo"


# ── Routed text: valid Inbound XADDed to the target's inbound stream ──────────


def test_text_with_target_xadds_valid_inbound_and_skips(
    redis: RouterRedis, state: RoutingState
) -> None:
    state.set_target("u-42", "mimir", "chan-1", "foo")
    event = _MockEvent(text="what's the status of pr 117", message_type="text")

    result = _call(event, redis=redis, state=state)

    assert result is not None
    assert result["action"] == "skip"
    assert result["reason"] == "routed to foo"

    # A single VALID Inbound landed on cc-sessions:foo:inbound.
    inbounds = _read_inbound(redis, "foo")
    assert len(inbounds) == 1
    msg = inbounds[0]
    assert isinstance(msg, Inbound)
    assert msg.text == "what's the status of pr 117"
    assert msg.source == "dm"  # "text" maps to dm
    assert msg.chat_id == "chan-1"
    assert msg.user_id == "u-42"
    assert msg.username == "jeff"
    assert msg.endpoint == "mimir"
    assert msg.router == "hermes-claude-code-router"
    assert msg.v == 1


def test_voice_message_type_maps_to_voice_source(
    redis: RouterRedis, state: RoutingState
) -> None:
    state.set_target("u-42", "mimir", "chan-1", "foo")
    event = _MockEvent(text="deploy the thing", message_type="voice")
    _call(event, redis=redis, state=state)
    inbounds = _read_inbound(redis, "foo")
    assert len(inbounds) == 1
    assert inbounds[0].source == "voice"


# ── No target: pass through to Mimir's LLM ───────────────────────────────────


def test_text_without_target_returns_none(
    redis: RouterRedis, state: RoutingState
) -> None:
    event = _MockEvent(text="just chatting with mimir")
    assert _call(event, redis=redis, state=state) is None
    # Nothing was XADDed anywhere.
    assert _read_inbound(redis, "foo") == []


# ── Disconnect: clears the target ────────────────────────────────────────────


def test_disconnect_phrase_clears_target_and_skips(
    redis: RouterRedis, state: RoutingState
) -> None:
    state.set_target("u-42", "mimir", "chan-1", "foo")
    event = _MockEvent(text="disconnect")

    result = _call(event, redis=redis, state=state)

    assert result == {"action": "skip", "reason": "routing target cleared"}
    assert state.get_target("u-42", "mimir", "chan-1") is None
    # A subsequent plain message now passes through (no target).
    assert _call(_MockEvent(text="hi"), redis=redis, state=state) is None


# ── Malformed payload: logged + dropped, hook returns cleanly ────────────────


def test_inbound_validation_failure_is_dropped_cleanly(
    redis: RouterRedis,
    state: RoutingState,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    state.set_target("u-42", "mimir", "chan-1", "foo")

    # Force Inbound construction to raise (simulating a payload that fails
    # protocol validation) — the hook must catch it, log, and return a clean skip.
    def _boom(*_a: Any, **_kw: Any) -> Inbound:
        raise ValueError("synthetic validation failure")

    monkeypatch.setattr(router_mod, "Inbound", _boom)

    event = _MockEvent(text="this will fail validation")
    with caplog.at_level("ERROR"):
        result = _call(event, redis=redis, state=state)

    # Hook returned cleanly (no exception), nothing was XADDed.
    assert result == {"action": "skip", "reason": "inbound validation failed; dropped"}
    assert _read_inbound(redis, "foo") == []
    assert any("dropped malformed inbound" in r.message for r in caplog.records)


# ── Gateway capture on first call ────────────────────────────────────────────


def test_gateway_is_captured_on_first_call(
    redis: RouterRedis, state: RoutingState, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Reset the module-level capture so this test is deterministic in isolation.
    monkeypatch.setattr(router_mod, "_gateway", None)
    gw = _MockGateway()
    event = _MockEvent(text="just chatting")  # pass-through path is fine

    _call(event, redis=redis, state=state, gateway=gw)

    assert router_mod.get_captured_gateway() is gw


# ── Targeted surface but no routable text → pass through ──────────────────────


def test_target_set_but_blank_text_passes_through(
    redis: RouterRedis, state: RoutingState
) -> None:
    state.set_target("u-42", "mimir", "chan-1", "foo")
    event = _MockEvent(text="   ", message_type="text")
    assert _call(event, redis=redis, state=state) is None
    assert _read_inbound(redis, "foo") == []


# ── Missing surface identity → pass through ───────────────────────────────────


def test_missing_user_or_chat_id_passes_through(
    redis: RouterRedis, state: RoutingState
) -> None:
    event = _MockEvent(text="connect to session foo", source=_MockSource(user_id=""))
    # Empty user_id falsy → treated as missing → pass through (no skip, no XADD).
    # source.user_id="" is falsy, so _user_id_from_event falls back to author_id
    # (absent) → None.
    object.__setattr__(event.source, "user_id", None)
    assert _call(event, redis=redis, state=state) is None
