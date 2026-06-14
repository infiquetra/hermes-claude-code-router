"""Redis connection helper + stream envelope for the router side.

This is the router's counterpart to ``redis-channel/server/redis_client.py``
(the CC plugin side). It centralizes:

* Connecting from ``REDIS_URL`` + URL-encoded ``REDIS_PASSWORD`` env vars.
* A thin, typed surface over the handful of Redis ops the router needs
  (``xadd``, ``xreadgroup``, ``hgetall``, ``exists``).
* The **stream envelope** — the single ``payload`` field carrying a
  canonically-serialized JSON object. This MUST stay byte-compatible with the
  redis-channel producer/consumer (``redis_producer.publish_outbound`` /
  ``redis_consumer.Consumer._dispatch``) so the two repos interoperate:

      XADD <stream> * payload <json.dumps(obj, separators=(",",":"), sort_keys=True)>

  Mirroring that exact encoding (compact separators, sorted keys, one opaque
  ``payload`` field — never spread across multiple Redis fields) is what lets a
  router XADD land in a CC consumer and vice versa.

The router reads CC → router streams (``outbound``, ``permission_request``)
via consumer group ``hermes-router``; group creation is idempotent.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any, TypeVar
from urllib.parse import quote, urlparse, urlunparse

import redis
import redis.exceptions
from pydantic import BaseModel

if TYPE_CHECKING:
    from collections.abc import Sequence

ModelT = TypeVar("ModelT", bound=BaseModel)

# Consumer group the router attaches to on CC → router streams. The CC side
# (PROTOCOL.md "Consumer groups") expects the router to read with a stable
# group name; "hermes-router" is the reference router's group.
ROUTER_GROUP = "hermes-router"
ROUTER_CONSUMER_DEFAULT = "consumer-1"

# Default stream cap, mirroring redis-channel's producer (avoid unbounded growth).
DEFAULT_MAXLEN = 10_000

_REDIS_URL_ENV = "REDIS_URL"
_REDIS_PASSWORD_ENV = "REDIS_PASSWORD"


def _resolve_url_from_env(
    *,
    url_env: str = _REDIS_URL_ENV,
    password_env: str = _REDIS_PASSWORD_ENV,
) -> str:
    """Build a Redis URL from env, injecting a URL-encoded password if present.

    ``REDIS_URL`` is required; a missing or empty value raises a clear error
    rather than silently defaulting to localhost. ``REDIS_PASSWORD`` is
    optional — when set, it is URL-encoded (``quote(..., safe="")``) and spliced
    into the URL's netloc so special chars (``:``, ``@``, ``/``, ``#``, ``?`` —
    common in base64-style 44-char Redis passwords) don't break redis-py's URL
    parser. A password already embedded in ``REDIS_URL`` is left untouched.
    """
    url = os.environ.get(url_env)
    if not url:
        raise RuntimeError(
            f"{url_env} is unset or empty; the router needs a Redis URL "
            f"(e.g. redis://host:6379/0). Set {url_env} in the environment."
        )

    password = os.environ.get(password_env)
    if not password:
        return url

    parsed = urlparse(url)
    if parsed.password:
        # Password already in the URL; don't double-inject.
        return url

    raw_user = parsed.username or ""
    user = quote(raw_user, safe="")
    encoded_password = quote(password, safe="")
    host = parsed.hostname or ""
    port_suffix = f":{parsed.port}" if parsed.port else ""
    auth_prefix = f"{user}:{encoded_password}@" if user else f":{encoded_password}@"
    netloc = f"{auth_prefix}{host}{port_suffix}"
    return urlunparse(parsed._replace(netloc=netloc))


def encode_envelope(payload: dict[str, Any]) -> dict[str, str]:
    """Wrap a payload dict into the single-field stream envelope.

    Byte-identical to redis-channel's producer: compact separators + sorted
    keys, stuffed into one ``payload`` field. Keeping it opaque (not spread
    across fields) means consumers never special-case field-set differences.
    """
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return {"payload": body}


def decode_envelope(fields: dict[str, Any]) -> dict[str, Any]:
    """Decode a stream entry's fields back into the payload dict.

    Raises ``ValueError`` if the ``payload`` field is missing, not valid JSON,
    or not a JSON object — the router treats these as malformed and should drop
    them (matching the CC consumer's defensive parsing).
    """
    raw = fields.get("payload")
    if raw is None:
        raise ValueError("stream entry missing 'payload' field")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"stream entry 'payload' is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("stream entry 'payload' did not decode to a JSON object")
    return payload


class RouterRedis:
    """Thin Redis surface for the router.

    Wraps a ``redis.Redis`` (or ``fakeredis.FakeRedis``) client with the small
    set of ops the router needs, plus model-aware stream helpers. Construct via
    :meth:`from_env` in production; pass an explicit client in tests.
    """

    def __init__(self, client: Any, *, group: str = ROUTER_GROUP) -> None:
        self._client = client
        self._group = group

    @classmethod
    def from_env(
        cls,
        *,
        group: str = ROUTER_GROUP,
        socket_timeout: float = 5.0,
        ping: bool = True,
    ) -> RouterRedis:
        """Connect from ``REDIS_URL`` + ``REDIS_PASSWORD`` and return a wrapper.

        Raises ``RuntimeError`` if ``REDIS_URL`` is unset. Pings by default so
        auth/network failures surface at construction, not first use.
        """
        url = _resolve_url_from_env()
        client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_timeout,
        )
        if ping:
            client.ping()
        return cls(client, group=group)

    @property
    def client(self) -> Any:
        """The underlying Redis client (for ops not on this thin surface)."""
        return self._client

    @property
    def group(self) -> str:
        return self._group

    # ── Thin passthrough ops ────────────────────────────────────────────────

    def xadd(
        self,
        stream: str,
        payload: dict[str, Any],
        *,
        maxlen: int = DEFAULT_MAXLEN,
        approximate: bool = True,
    ) -> str:
        """XADD a payload onto ``stream`` using the shared envelope.

        ``payload`` is the decoded dict; it is wrapped via :func:`encode_envelope`
        before XADD so the wire format matches redis-channel. Returns the
        assigned message ID.
        """
        raw_id = self._client.xadd(
            stream,
            encode_envelope(payload),
            maxlen=maxlen,
            approximate=approximate,
        )
        return str(raw_id)

    def ensure_group(self, stream: str, *, start: str = "0") -> bool:
        """Create the router consumer group on ``stream`` if absent.

        Idempotent: a ``BUSYGROUP`` error (group already exists) is swallowed.
        ``start="0"`` (the default) delivers the full backlog the first time the
        group is created — the router lazily creates its group on first read, so
        ``"0"`` avoids silently skipping messages a CC session XADDed before the
        router attached. Pass ``start="$"`` to attach at the tail instead.
        ``mkstream`` creates the stream if it doesn't exist yet. Returns True if
        the group was newly created, False if it already existed.
        """
        try:
            self._client.xgroup_create(
                name=stream, groupname=self._group, id=start, mkstream=True
            )
            return True
        except redis.exceptions.ResponseError as exc:
            if "BUSYGROUP" in str(exc):
                return False
            raise

    def xreadgroup(
        self,
        streams: Sequence[str] | str,
        *,
        consumer: str = ROUTER_CONSUMER_DEFAULT,
        count: int = 16,
        block_ms: int = 1000,
        last_id: str = ">",
    ) -> list[tuple[str, list[tuple[str, dict[str, Any]]]]]:
        """XREADGROUP over one or more streams via the ``hermes-router`` group.

        Creates the group on each stream first (idempotent), so callers never
        hit NOGROUP. Returns the raw redis-py response shape:
        ``[(stream, [(msg_id, {field: value}), ...]), ...]`` (empty list on no
        new messages). Use :meth:`read_models` for typed parsing.
        """
        stream_list = [streams] if isinstance(streams, str) else list(streams)
        for stream in stream_list:
            self.ensure_group(stream)
        resp = self._client.xreadgroup(
            groupname=self._group,
            consumername=consumer,
            streams=dict.fromkeys(stream_list, last_id),
            count=count,
            block=block_ms,
        )
        return resp or []

    def ack(self, stream: str, msg_id: str) -> int:
        """XACK a processed message on ``stream`` for the router group."""
        return int(self._client.xack(stream, self._group, msg_id))

    def hgetall(self, key: str) -> dict[str, Any]:
        """HGETALL a hash (e.g. ``cc-sessions:registry``)."""
        result = self._client.hgetall(key)
        return dict(result) if result else {}

    def exists(self, key: str) -> bool:
        """EXISTS check (e.g. ``cc-sessions:hb:<name>`` for live presence)."""
        return bool(self._client.exists(key))

    # ── Model-aware stream helpers ──────────────────────────────────────────

    def xadd_model(
        self,
        stream: str,
        model: BaseModel,
        *,
        maxlen: int = DEFAULT_MAXLEN,
        approximate: bool = True,
    ) -> str:
        """XADD a protocol model (e.g. :class:`Inbound`) onto ``stream``.

        The model is dumped with ``mode="json"`` so enums/floats serialize the
        way the JSON envelope expects, then wrapped in the shared envelope.
        """
        payload = model.model_dump(mode="json")
        return self.xadd(stream, payload, maxlen=maxlen, approximate=approximate)

    def read_models(
        self,
        stream: str,
        model_cls: type[ModelT],
        *,
        consumer: str = ROUTER_CONSUMER_DEFAULT,
        count: int = 16,
        block_ms: int = 1000,
        last_id: str = ">",
    ) -> list[tuple[str, ModelT]]:
        """XREADGROUP a single stream and parse each entry into ``model_cls``.

        Returns ``[(msg_id, model), ...]``. The Redis stream message ID is
        attached to the payload as ``_msg_id`` before validation (mirroring the
        CC consumer) so callers can correlate replies / XACK. Entries with a
        malformed envelope are skipped (the router drops, never crashes).
        """
        resp = self.xreadgroup(
            stream,
            consumer=consumer,
            count=count,
            block_ms=block_ms,
            last_id=last_id,
        )
        out: list[tuple[str, ModelT]] = []
        for _stream_name, entries in resp:
            for msg_id, fields in entries:
                try:
                    payload = decode_envelope(fields)
                except ValueError:
                    continue
                payload.setdefault("_msg_id", msg_id)
                out.append((msg_id, model_cls.model_validate(payload)))
        return out
