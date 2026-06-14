"""Tests for the presence-aware registry reader.

Uses fakeredis — no real Redis, no real Hermes. The reader filters the
``cc-sessions:registry`` hash through heartbeat presence
(``EXISTS cc-sessions:hb:<name>``) and lazy-ignores malformed entries, so the
core cases are: only-heartbeat-backed entries survive, an empty registry is
``[]``, and one junk JSON value is logged-and-skipped without dropping the rest.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import fakeredis
import pytest

from hermes_claude_code_router.protocol import RegistryEntry
from hermes_claude_code_router.redis_client import RouterRedis
from hermes_claude_code_router.registry_reader import (
    HEARTBEAT_TTL_SECONDS,
    REGISTRY_KEY,
    heartbeat_key,
    list_live_sessions,
)


@pytest.fixture
def fake_client() -> Any:
    """A fresh fakeredis client with decode_responses (matches prod connect)."""
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def router(fake_client: Any) -> RouterRedis:
    return RouterRedis(fake_client)


def _entry(session_name: str, *, cwd: str = "/Users/jefcox/workspace/demo") -> RegistryEntry:
    return RegistryEntry(
        session_name=session_name,
        host="jeffs-mac-mini.local",
        cwd=cwd,
        git_branch="feat/v1-spine",
        pid=4242,
        started_at=1716567890.0,
        capabilities=["reply", "permission"],
    )


def _register(
    fake_client: Any, entry: RegistryEntry, *, with_heartbeat: bool
) -> None:
    """HSET the registry field; optionally SET the hb key with EX 60."""
    fake_client.hset(
        REGISTRY_KEY,
        entry.session_name,
        json.dumps(entry.model_dump(mode="json")),
    )
    if with_heartbeat:
        fake_client.set(
            heartbeat_key(entry.session_name),
            "2026-06-14T00:00:00Z",
            ex=HEARTBEAT_TTL_SECONDS,
        )


# ── Presence filtering ───────────────────────────────────────────────────────


def test_only_heartbeat_backed_session_returned(
    router: RouterRedis, fake_client: Any
) -> None:
    live_entry = _entry("demo-live-a1b2")
    dead_entry = _entry("demo-dead-c3d4")
    _register(fake_client, live_entry, with_heartbeat=True)
    _register(fake_client, dead_entry, with_heartbeat=False)

    sessions = list_live_sessions(router)

    assert len(sessions) == 1
    assert sessions[0]["session_name"] == "demo-live-a1b2"


def test_projection_shape_and_values(router: RouterRedis, fake_client: Any) -> None:
    _register(
        fake_client,
        _entry("demo-live-a1b2", cwd="/Users/jefcox/workspace/demo/"),
        with_heartbeat=True,
    )

    (session,) = list_live_sessions(router)

    assert set(session.keys()) == {
        "session_name",
        "cwd_basename",
        "git_branch",
        "started_at",
        "last_seen_seconds",
    }
    assert session["cwd_basename"] == "demo"  # basename, trailing slash stripped
    assert session["git_branch"] == "feat/v1-spine"
    assert session["started_at"] == pytest.approx(1716567890.0)
    # Fresh beat (EX 60, full TTL) → ~0s since last seen, clamped to >= 0.
    assert session["last_seen_seconds"] == pytest.approx(0.0, abs=1.0)


def test_empty_registry_returns_empty_list(router: RouterRedis) -> None:
    assert list_live_sessions(router) == []


# ── Lazy-ignore of malformed entries ─────────────────────────────────────────


def test_malformed_json_value_is_skipped_others_survive(
    router: RouterRedis, fake_client: Any, caplog: pytest.LogCaptureFixture
) -> None:
    good = _entry("demo-good-1111")
    _register(fake_client, good, with_heartbeat=True)
    # A junk (non-JSON) registry value, with a heartbeat so presence isn't the
    # thing filtering it out — the JSON parse is.
    fake_client.hset(REGISTRY_KEY, "demo-bad-2222", "{not valid json")
    fake_client.set(heartbeat_key("demo-bad-2222"), "ts", ex=HEARTBEAT_TTL_SECONDS)

    with caplog.at_level(logging.WARNING):
        sessions = list_live_sessions(router)

    assert [s["session_name"] for s in sessions] == ["demo-good-1111"]
    assert "demo-bad-2222" in caplog.text
    assert "malformed JSON" in caplog.text


def test_schema_invalid_value_is_skipped_others_survive(
    router: RouterRedis, fake_client: Any, caplog: pytest.LogCaptureFixture
) -> None:
    good = _entry("demo-good-1111")
    _register(fake_client, good, with_heartbeat=True)
    # Valid JSON, but missing required RegistryEntry fields (pid/host/...).
    fake_client.hset(
        REGISTRY_KEY, "demo-invalid-3333", json.dumps({"session_name": "x"})
    )
    fake_client.set(
        heartbeat_key("demo-invalid-3333"), "ts", ex=HEARTBEAT_TTL_SECONDS
    )

    with caplog.at_level(logging.WARNING):
        sessions = list_live_sessions(router)

    assert [s["session_name"] for s in sessions] == ["demo-good-1111"]
    assert "demo-invalid-3333" in caplog.text
    assert "failed RegistryEntry validation" in caplog.text


def test_last_seen_none_when_heartbeat_has_no_expiry(
    router: RouterRedis, fake_client: Any
) -> None:
    entry = _entry("demo-noexpiry-9999")
    fake_client.hset(
        REGISTRY_KEY, entry.session_name, json.dumps(entry.model_dump(mode="json"))
    )
    # Heartbeat key exists but without a TTL (TTL == -1) → age uncomputable.
    fake_client.set(heartbeat_key(entry.session_name), "ts")

    (session,) = list_live_sessions(router)

    assert session["last_seen_seconds"] is None
