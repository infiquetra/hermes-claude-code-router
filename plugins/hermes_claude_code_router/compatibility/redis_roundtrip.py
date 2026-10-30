"""Explicit real-Redis acceptance; deliberately outside pytest discovery.

Run as a module from the repository root with --port for an owned ephemeral
Redis service. There is no default port, environment URL, skip, or fake backend.
"""

from __future__ import annotations

import argparse
import time
from uuid import uuid4

import redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from ..protocol import Outbound
from ..redis_client import RouterRedis


def check_roundtrip(port: int) -> None:
    """Prove stream serialization, group delivery, acknowledgement and cleanup."""
    session = f"compatibility-{uuid4().hex}"
    stream = f"cc-sessions:{session}:outbound"
    sent = Outbound(
        session_name=session,
        endpoint="compatibility",
        chat_id="test-chat",
        text="Redis stream round trip: \u2713\nsecond line",
        ts=time.time(),
    )
    # A fixed loopback host and mandatory port avoid inheriting production targets.
    with redis.Redis(
        host="127.0.0.1",
        port=port,
        decode_responses=True,
        socket_timeout=2.0,
        socket_connect_timeout=2.0,
        retry=Retry(NoBackoff(), 0),
    ) as client:
        router = RouterRedis(client)
        try:
            msg_id = router.xadd_model(stream, sent)
            messages = router.read_models(stream, Outbound, count=1, block_ms=100)
            assert len(messages) == 1, "Expected one stream message"
            read_id, received = messages[0]
            assert read_id == msg_id, "Stream message ID changed"
            assert getattr(received, "_msg_id", None) == msg_id, "Missing delivery ID"
            assert received.model_dump(exclude={"_msg_id"}) == sent.model_dump(), (
                "Protocol payload changed in transit"
            )
            assert client.xpending(stream, router.group)["pending"] == 1, (
                "Delivery must enter the pending entries list"
            )
            assert router.ack(stream, msg_id) == 1, "Acknowledgement failed"
            assert client.xpending(stream, router.group)["pending"] == 0, (
                "Acknowledged delivery is still pending"
            )
            assert router.ack(stream, msg_id) == 0, "Acknowledgement is not idempotent"
        finally:
            # Delete only this invocation's stream, including its consumer group.
            client.delete(stream)
            assert not router.exists(stream), "Temporary stream cleanup failed"
    print("Real Redis stream compatibility passed: write, read, payload, ack, cleanup")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True, help="Owned loopback Redis test port")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    check_roundtrip(args.port)


if __name__ == "__main__":
    main()
