"""Tests for the router's Redis client + stream envelope.

Uses fakeredis — no real Redis, no real Discord, no real Hermes. The envelope
encoding is asserted byte-for-byte against the redis-channel producer contract
(single ``payload`` field, compact separators, sorted keys) so the two repos
stay interoperable.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import unquote, urlparse

import fakeredis
import pytest

from hermes_claude_code_router.protocol import Inbound
from hermes_claude_code_router.redis_client import (
    ROUTER_GROUP,
    RouterRedis,
    _resolve_url_from_env,
    decode_envelope,
    encode_envelope,
)


@pytest.fixture
def fake_client() -> Any:
    """A fresh fakeredis client with decode_responses (matches prod connect)."""
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def router(fake_client: Any) -> RouterRedis:
    return RouterRedis(fake_client)


def _sample_inbound() -> Inbound:
    return Inbound(
        router="hermes-claude-code-router",
        endpoint="mimir",
        source="voice",
        chat_id="vc-123",
        user_id="u-456",
        username="jeff",
        text="what's the status of pr 117",
        confidence=0.93,
        ts=1716567890.0,
    )


# ── Env / URL resolution ────────────────────────────────────────────────────


def test_missing_redis_url_raises_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)
    with pytest.raises(RuntimeError) as exc:
        _resolve_url_from_env()
    assert "REDIS_URL" in str(exc.value)


def test_empty_redis_url_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", "")
    with pytest.raises(RuntimeError):
        _resolve_url_from_env()


def test_no_password_returns_url_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://example.com:6379/0")
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)
    assert _resolve_url_from_env() == "redis://example.com:6379/0"


def test_password_with_special_chars_is_url_encoded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A password full of chars that would otherwise break redis-py's URL parser.
    secret = "p@ss:w/rd#?=+&"
    monkeypatch.setenv("REDIS_URL", "redis://cache.internal:6380/2")
    monkeypatch.setenv("REDIS_PASSWORD", secret)

    resolved = _resolve_url_from_env()

    # No raw special chars leaked into the URL — they're percent-encoded.
    assert "p@ss:w/rd#?=+&" not in resolved
    assert "%40" in resolved  # @
    assert "%2F" in resolved  # /
    assert "%23" in resolved  # #

    # And the URL must still parse cleanly. urlparse keeps the password in its
    # percent-encoded form; unquoting it must recover the original secret
    # (redis-py does this decode on connect).
    parsed = urlparse(resolved)
    assert parsed.hostname == "cache.internal"
    assert parsed.port == 6380
    assert parsed.password is not None
    assert unquote(parsed.password) == secret


def test_password_not_double_injected_if_already_in_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://:already@host:6379/0")
    monkeypatch.setenv("REDIS_PASSWORD", "ignored")
    assert _resolve_url_from_env() == "redis://:already@host:6379/0"


# ── Envelope encoding (byte-compat with redis-channel) ──────────────────────


def test_encode_envelope_is_single_payload_field() -> None:
    env = encode_envelope({"b": 2, "a": 1})
    assert set(env.keys()) == {"payload"}
    # Compact separators + sorted keys, mirroring redis_producer.publish_outbound.
    assert env["payload"] == '{"a":1,"b":2}'


def test_decode_envelope_round_trips() -> None:
    payload = {"a": 1, "nested": {"x": [1, 2, 3]}}
    assert decode_envelope(encode_envelope(payload)) == payload


def test_decode_envelope_missing_payload_field_raises() -> None:
    with pytest.raises(ValueError, match="missing 'payload'"):
        decode_envelope({"not_payload": "x"})


def test_decode_envelope_bad_json_raises() -> None:
    with pytest.raises(ValueError, match="not valid JSON"):
        decode_envelope({"payload": "{not json"})


def test_decode_envelope_non_object_raises() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        decode_envelope({"payload": "[1, 2, 3]"})


# ── xadd → xreadgroup round-trip ────────────────────────────────────────────


def test_xadd_xreadgroup_round_trips_model(router: RouterRedis) -> None:
    stream = "cc-sessions:test-session:inbound"
    sent = _sample_inbound()

    msg_id = router.xadd_model(stream, sent)
    assert msg_id  # non-empty redis stream id

    got = router.read_models(stream, Inbound, block_ms=10)
    assert len(got) == 1
    read_id, model = got[0]
    assert read_id == msg_id
    assert model.text == sent.text
    assert model.source == "voice"
    assert model.confidence == pytest.approx(0.93)
    assert model.endpoint == "mimir"
    # _msg_id is stitched in (extra="allow" on the model permits it).
    assert getattr(model, "_msg_id", None) == msg_id


def test_xadd_raw_payload_decodes_via_thin_methods(router: RouterRedis) -> None:
    stream = "cc-sessions:s:outbound"
    msg_id = router.xadd(stream, {"hello": "world", "n": 7})
    resp = router.xreadgroup(stream, block_ms=10)
    assert len(resp) == 1
    _name, entries = resp[0]
    assert len(entries) == 1
    got_id, fields = entries[0]
    assert got_id == msg_id
    assert decode_envelope(fields) == {"hello": "world", "n": 7}


def test_read_models_skips_malformed_entries(
    router: RouterRedis, fake_client: Any
) -> None:
    stream = "cc-sessions:s:inbound"
    router.ensure_group(stream)
    # Directly XADD a junk envelope (bypassing our encoder) + a valid one.
    fake_client.xadd(stream, {"payload": "{broken"})
    good_id = router.xadd_model(stream, _sample_inbound())

    got = router.read_models(stream, Inbound, block_ms=10)
    # Only the valid entry survives; the broken one is dropped, not raised.
    assert len(got) == 1
    assert got[0][0] == good_id


# ── Consumer-group idempotency ──────────────────────────────────────────────


def test_ensure_group_idempotent(router: RouterRedis) -> None:
    stream = "cc-sessions:s:outbound"
    first = router.ensure_group(stream)
    second = router.ensure_group(stream)
    assert first is True  # newly created
    assert second is False  # already exists, no-op


def test_xreadgroup_creates_group_if_missing(router: RouterRedis) -> None:
    # Never call ensure_group explicitly — xreadgroup must auto-create so we
    # never hit NOGROUP on a cold stream.
    stream = "cc-sessions:cold:outbound"
    resp = router.xreadgroup(stream, block_ms=10)
    assert resp == []  # no messages, but no NOGROUP error either


def test_default_group_is_hermes_router(router: RouterRedis) -> None:
    assert router.group == ROUTER_GROUP == "hermes-router"


def test_ack_marks_message_processed(router: RouterRedis) -> None:
    stream = "cc-sessions:s:outbound"
    msg_id = router.xadd(stream, {"x": 1})
    # Deliver into the PEL via the thin (non-validating) read.
    resp = router.xreadgroup(stream, block_ms=10)
    assert resp and resp[0][1][0][0] == msg_id
    # Now pending; ack removes it from the PEL and reports 1 message acked.
    assert router.ack(stream, msg_id) == 1
    # Re-acking the same id is a no-op (already removed from PEL).
    assert router.ack(stream, msg_id) == 0


# ── hgetall / exists thin passthroughs ──────────────────────────────────────


def test_hgetall_returns_dict(router: RouterRedis, fake_client: Any) -> None:
    fake_client.hset("cc-sessions:registry", "sess-a", json.dumps({"v": 1}))
    out = router.hgetall("cc-sessions:registry")
    assert out == {"sess-a": '{"v": 1}'}


def test_hgetall_missing_key_returns_empty(router: RouterRedis) -> None:
    assert router.hgetall("cc-sessions:registry") == {}


def test_exists_reflects_presence(router: RouterRedis, fake_client: Any) -> None:
    hb = "cc-sessions:hb:sess-a"
    assert router.exists(hb) is False
    fake_client.set(hb, "2026-06-14T00:00:00Z")
    assert router.exists(hb) is True
