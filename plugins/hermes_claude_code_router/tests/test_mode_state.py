"""Tests for the in-memory routing-target state (mode_state.RoutingState)."""

from __future__ import annotations

import pytest

from hermes_claude_code_router.mode_state import RoutingState


@pytest.fixture
def state() -> RoutingState:
    return RoutingState()


def test_set_then_get_returns_target(state: RoutingState) -> None:
    state.set_target("u1", "mimir", "c1", "session-alpha")
    assert state.get_target("u1", "mimir", "c1") == "session-alpha"


def test_get_unset_returns_none(state: RoutingState) -> None:
    assert state.get_target("u1", "mimir", "c1") is None


def test_clear_then_get_returns_none(state: RoutingState) -> None:
    state.set_target("u1", "mimir", "c1", "session-alpha")
    state.clear_target("u1", "mimir", "c1")
    assert state.get_target("u1", "mimir", "c1") is None


def test_clear_unset_is_noop(state: RoutingState) -> None:
    # Clearing a key that was never set must not raise.
    state.clear_target("u1", "mimir", "c1")
    assert state.get_target("u1", "mimir", "c1") is None


def test_set_target_overwrites(state: RoutingState) -> None:
    state.set_target("u1", "mimir", "c1", "session-alpha")
    state.set_target("u1", "mimir", "c1", "session-beta")
    assert state.get_target("u1", "mimir", "c1") == "session-beta"


def test_distinct_keys_do_not_collide(state: RoutingState) -> None:
    state.set_target("u1", "mimir", "c1", "session-alpha")
    state.set_target("u2", "mimir", "c1", "session-beta")
    assert state.get_target("u1", "mimir", "c1") == "session-alpha"
    assert state.get_target("u2", "mimir", "c1") == "session-beta"


def test_distinct_keys_by_endpoint_and_chat(state: RoutingState) -> None:
    state.set_target("u1", "mimir", "c1", "alpha")
    state.set_target("u1", "other", "c1", "beta")
    state.set_target("u1", "mimir", "c2", "gamma")
    assert state.get_target("u1", "mimir", "c1") == "alpha"
    assert state.get_target("u1", "other", "c1") == "beta"
    assert state.get_target("u1", "mimir", "c2") == "gamma"


def test_routing_on_by_default(state: RoutingState) -> None:
    assert state.is_routing_on("u1", "mimir", "c1") is True


def test_routing_off_suppresses_target_resolution(state: RoutingState) -> None:
    state.set_target("u1", "mimir", "c1", "session-alpha")
    state.set_routing("u1", "mimir", "c1", enabled=False)
    assert state.is_routing_on("u1", "mimir", "c1") is False
    assert state.get_target("u1", "mimir", "c1") is None


def test_routing_back_on_restores_target(state: RoutingState) -> None:
    state.set_target("u1", "mimir", "c1", "session-alpha")
    state.set_routing("u1", "mimir", "c1", enabled=False)
    assert state.get_target("u1", "mimir", "c1") is None
    state.set_routing("u1", "mimir", "c1", enabled=True)
    assert state.get_target("u1", "mimir", "c1") == "session-alpha"


def test_routing_off_is_per_key(state: RoutingState) -> None:
    state.set_target("u1", "mimir", "c1", "alpha")
    state.set_target("u2", "mimir", "c1", "beta")
    state.set_routing("u1", "mimir", "c1", enabled=False)
    # u1's surface is suppressed; u2's is unaffected.
    assert state.get_target("u1", "mimir", "c1") is None
    assert state.get_target("u2", "mimir", "c1") == "beta"
    assert state.is_routing_on("u2", "mimir", "c1") is True
