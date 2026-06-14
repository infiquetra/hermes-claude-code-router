"""Tests for the U6 outbound relay (fakeredis + injected/mocked Discord surface)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import fakeredis
import pytest

from hermes_claude_code_router.outbound import OutboundRelay, send_coro
from hermes_claude_code_router.protocol import Outbound
from hermes_claude_code_router.redis_client import ROUTER_GROUP, RouterRedis


@pytest.fixture
def router() -> RouterRedis:
    return RouterRedis(fakeredis.FakeRedis(decode_responses=True), group=ROUTER_GROUP)


def _outbound(session: str, chat_id: str, text: str, in_reply_to: str | None = None) -> Outbound:
    return Outbound(
        session_name=session,
        endpoint="mimir",
        chat_id=chat_id,
        text=text,
        in_reply_to=in_reply_to,
        ts=time.time(),
    )


# ── poll_once: reconcile + drain ──────────────────────────────────────────────


def test_poll_once_delivers_active_targets_and_acks(router: RouterRedis) -> None:
    router.xadd_model("cc-sessions:foo:outbound", _outbound("foo", "111", "hello from foo"))
    router.xadd_model("cc-sessions:bar:outbound", _outbound("bar", "222", "hello from bar"))
    sent: list[Outbound] = []
    relay = OutboundRelay(router, lambda: {"foo", "bar"}, lambda: object(), sender=sent.append)

    delivered = relay.poll_once()

    assert delivered == 2
    assert {o.chat_id for o in sent} == {"111", "222"}
    # Both entries ACKed → nothing left pending for the group.
    for stream in ("cc-sessions:foo:outbound", "cc-sessions:bar:outbound"):
        assert router.client.xpending(stream, ROUTER_GROUP)["pending"] == 0


def test_poll_once_no_active_targets_is_noop(router: RouterRedis) -> None:
    sent: list[Outbound] = []
    relay = OutboundRelay(router, set, lambda: object(), sender=sent.append)
    assert relay.poll_once() == 0
    assert sent == []


def test_inactive_target_is_not_consumed(router: RouterRedis) -> None:
    # A reply waits on foo's stream, but only bar is active (foo disconnected).
    router.xadd_model("cc-sessions:foo:outbound", _outbound("foo", "111", "stale"))
    sent: list[Outbound] = []
    relay = OutboundRelay(router, lambda: {"bar"}, lambda: object(), sender=sent.append)
    assert relay.poll_once() == 0
    assert sent == []


def test_malformed_entry_dropped_and_acked(router: RouterRedis) -> None:
    # Raw XADD bypassing the envelope helper → undecodable payload.
    router.client.xadd("cc-sessions:foo:outbound", {"payload": "not-json"})
    sent: list[Outbound] = []
    relay = OutboundRelay(router, lambda: {"foo"}, lambda: object(), sender=sent.append)

    assert relay.poll_once() == 0
    assert sent == []
    assert router.client.xpending("cc-sessions:foo:outbound", ROUTER_GROUP)["pending"] == 0


# ── send_coro: surface-aware send ─────────────────────────────────────────────


class _FakeChannel:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []

    async def send(self, text: str, **kwargs: Any) -> None:
        self.sent.append((text, kwargs))

    async def fetch_message(self, mid: int) -> str:
        return f"msg-{mid}"


class _FakeClient:
    def __init__(self, cached: _FakeChannel | None, fetched: _FakeChannel | None) -> None:
        self._cached = cached
        self._fetched = fetched
        self.fetched_ids: list[Any] = []

    def get_channel(self, cid: Any) -> _FakeChannel | None:
        return self._cached

    async def fetch_channel(self, cid: Any) -> _FakeChannel:
        self.fetched_ids.append(cid)
        assert self._fetched is not None
        return self._fetched


def test_send_coro_guild_channel_uses_cache() -> None:
    ch = _FakeChannel()
    client = _FakeClient(cached=ch, fetched=None)
    asyncio.run(send_coro(client, "123", "hi", None))
    assert ch.sent == [("hi", {})]


def test_send_coro_dm_falls_back_to_fetch() -> None:
    # DM channel id not cached → get_channel None → fetch_channel resolves it.
    ch = _FakeChannel()
    client = _FakeClient(cached=None, fetched=ch)
    asyncio.run(send_coro(client, "999", "dm hi", None))
    assert ch.sent == [("dm hi", {})]
    assert client.fetched_ids == [999]


def test_send_coro_in_reply_to_non_discord_id_plain_send() -> None:
    # A Redis stream id ("1718-0") is not an int → reference resolution fails → plain send.
    ch = _FakeChannel()
    client = _FakeClient(cached=ch, fetched=None)
    asyncio.run(send_coro(client, "123", "threaded?", "1718-0"))
    assert ch.sent == [("threaded?", {})]


def test_send_coro_in_reply_to_resolvable_threads() -> None:
    ch = _FakeChannel()
    client = _FakeClient(cached=ch, fetched=None)
    asyncio.run(send_coro(client, "123", "reply", "456"))
    text, kwargs = ch.sent[0]
    assert text == "reply"
    assert kwargs.get("reference") == "msg-456"


# ── default send path: graceful degradation ──────────────────────────────────


def test_default_send_no_gateway_does_not_raise(router: RouterRedis) -> None:
    relay = OutboundRelay(router, lambda: {"foo"}, lambda: None)  # gateway never captured
    relay._deliver(_outbound("foo", "111", "x"))  # must not raise


# ── lifecycle ────────────────────────────────────────────────────────────────


def test_start_is_idempotent_and_stop_joins(router: RouterRedis) -> None:
    relay = OutboundRelay(router, set, lambda: object())  # idle (no active targets)
    relay.start()
    assert relay.running
    first = relay._thread
    relay.start()  # idempotent — no second thread
    assert relay._thread is first
    relay.stop()
    assert not relay.running
