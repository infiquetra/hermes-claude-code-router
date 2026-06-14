"""Outbound relay — delivers CC-session replies back to the originating surface.

The router has no ``gateway.send_message()``; out-of-band delivery reaches into
the platform adapter's underlying discord.py client and schedules a send on the
gateway's asyncio loop (LEARNINGS#outbound-text-via-discord-py).

Lifecycle. The plan's "per-target consumer, started when a target is set and the
gateway is captured, stopped on disconnect" is realized as a single reconciling
relay: one background thread polls the *active* routing targets'
``cc-sessions:<name>:outbound`` streams via the ``hermes-router`` consumer group,
parses each entry as an :class:`~.protocol.Outbound`, and schedules a
surface-aware send. A target enters the consumed set when it appears in
:meth:`RoutingState.active_targets` (connect) and leaves when it disappears
(disconnect) — so the per-target lifecycle is implicit in the reconcile, no
cross-module wiring from the router is needed.

The gateway is captured by the router hook on its first event (only reachable
there). Until it exists the relay idles. All Hermes/discord.py reach lives behind
small helpers (``_resolve_client`` / ``_resolve_loop`` / :func:`send_coro`) and an
injectable ``sender`` so tests mock it; the exact adapter internals are confirmed
against the live profile at the acceptance gate (KTD5).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any

from .protocol import Outbound
from .redis_client import RouterRedis, decode_envelope

logger = logging.getLogger(__name__)

GatewayProvider = Callable[[], Any]
ActiveTargetsProvider = Callable[[], set[str]]
Sender = Callable[[Outbound], None]

_SEND_TIMEOUT_SECONDS = 10.0
_IDLE_WAIT_SECONDS = 0.2


def _resolve_client(gateway: Any) -> Any | None:
    """Extract the underlying discord.py client from the gateway's adapter.

    The gateway is a thin orchestrator over platform adapters; the plugin reaches
    ``gateway.adapters["discord"]`` then its ``_client``/``client``
    (LEARNINGS#outbound-text-via-discord-py). Returns ``None`` if not resolvable.
    """
    adapters = getattr(gateway, "adapters", None)
    adapter = adapters.get("discord") if isinstance(adapters, dict) else None
    if adapter is None:
        adapter = getattr(gateway, "adapter", None)
    if adapter is None:
        return None
    return getattr(adapter, "_client", None) or getattr(adapter, "client", None)


def _resolve_loop(gateway: Any) -> Any | None:
    """Find the gateway's asyncio loop (``gateway.loop`` / ``._loop``)."""
    for attr in ("loop", "_loop"):
        loop = getattr(gateway, attr, None)
        if loop is not None:
            return loop
    return None


def _as_channel_id(chat_id: str) -> int | str:
    """Discord ids are ints; pass through non-numeric ids unchanged."""
    return int(chat_id) if chat_id.isdigit() else chat_id


async def send_coro(
    client: Any, chat_id: str, text: str, in_reply_to: str | None
) -> None:
    """Resolve the channel surface-agnostically and send ``text``.

    ``client.get_channel`` covers cached guild channels and threads;
    ``fetch_channel`` resolves anything not cached, including DM channels (for
    which ``get_channel`` returns ``None``). ``in_reply_to`` threading is
    best-effort — a non-Discord id (e.g. a Redis stream id) just falls back to an
    unthreaded send.
    """
    cid = _as_channel_id(chat_id)
    channel = client.get_channel(cid)
    if channel is None:
        channel = await client.fetch_channel(cid)
    kwargs: dict[str, Any] = {}
    if in_reply_to:
        try:
            kwargs["reference"] = await channel.fetch_message(int(in_reply_to))
        except Exception:  # noqa: BLE001 - best-effort threading; fall back to plain send
            logger.debug(
                "outbound: in_reply_to=%s not resolvable; sending unthreaded",
                in_reply_to,
            )
    await channel.send(text, **kwargs)


class OutboundRelay:
    """Reconciling consumer that delivers CC replies to Discord surfaces."""

    def __init__(
        self,
        redis: RouterRedis,
        active_targets: ActiveTargetsProvider,
        gateway_provider: GatewayProvider,
        *,
        sender: Sender | None = None,
        poll_block_ms: int = 1000,
    ) -> None:
        self._redis = redis
        self._active_targets = active_targets
        self._gateway_provider = gateway_provider
        self._sender = sender or self._default_send
        self._poll_block_ms = poll_block_ms
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the relay thread (idempotent — a live thread is left running)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="hermes-router-outbound", daemon=True
        )
        self._thread.start()

    def stop(self, *, timeout: float = 2.0) -> None:
        """Signal the relay thread to stop and join it."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── Reconcile + drain ──────────────────────────────────────────────────

    def poll_once(self) -> int:
        """One reconcile+drain pass; returns the number of replies delivered.

        Reads only the *currently active* targets' outbound streams, so a
        disconnected target is dropped from consumption automatically. Malformed
        entries are logged, ACKed (so they don't redeliver forever), and skipped.
        """
        targets = self._active_targets()
        if not targets:
            return 0
        streams = [f"cc-sessions:{t}:outbound" for t in sorted(targets)]
        delivered = 0
        for stream_name, entries in self._redis.xreadgroup(
            streams, block_ms=self._poll_block_ms
        ):
            for msg_id, fields in entries:
                try:
                    ob = Outbound.model_validate(decode_envelope(fields))
                except Exception:  # noqa: BLE001 - malformed (poison) → drop + ack so it can't redeliver forever
                    logger.warning(
                        "outbound: dropped malformed entry %s on %s", msg_id, stream_name
                    )
                    self._redis.ack(stream_name, msg_id)
                    continue
                try:
                    self._deliver(ob)
                except Exception:  # noqa: BLE001 - delivery failed → leave UNACKed (pending) for recovery
                    logger.warning(
                        "outbound: delivery failed for chat=%s on %s; left pending",
                        ob.chat_id,
                        stream_name,
                    )
                    continue
                self._redis.ack(stream_name, msg_id)
                delivered += 1
        return delivered

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                if self.poll_once() == 0:
                    self._stop.wait(_IDLE_WAIT_SECONDS)
            except Exception:  # noqa: BLE001 - never let the relay thread die on a transient error
                logger.exception("outbound relay poll failed; continuing")
                self._stop.wait(1.0)

    def _deliver(self, ob: Outbound) -> None:
        self._sender(ob)

    def _default_send(self, ob: Outbound) -> None:
        """Production delivery: schedule the send on the gateway's asyncio loop.

        Raises on any failure (no gateway captured yet, client/loop unresolvable,
        send error, or timeout) so :meth:`poll_once` leaves the entry pending
        (unacked) for recovery rather than ACKing a reply that never landed. On
        timeout the coroutine is cancelled so it cannot fire late as a duplicate.
        """
        gateway = self._gateway_provider()
        if gateway is None:
            raise RuntimeError("no gateway captured yet")
        client = _resolve_client(gateway)
        loop = _resolve_loop(gateway)
        if client is None or loop is None:
            raise RuntimeError("could not resolve discord client/loop")
        future = asyncio.run_coroutine_threadsafe(
            send_coro(client, ob.chat_id, ob.text, ob.in_reply_to), loop
        )
        try:
            future.result(timeout=_SEND_TIMEOUT_SECONDS)
        except FuturesTimeout:
            future.cancel()
            raise
