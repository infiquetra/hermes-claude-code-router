"""In-memory routing-target state for the Hermes router.

Per the project KTDs, routing-target state lives in plugin memory only — there
is NO Redis or file persistence. State is keyed by ``(user_id, endpoint,
chat_id)`` so each distinct conversation surface (a Discord DM, a voice channel,
a thread) tracks its own routing target and on/off flag independently.

Two pieces of state per key:
  - **target**: the ``session_name`` (a Claude Code session) that this surface's
    messages are currently routed to, or ``None`` if no target is set.
  - **routing flag**: whether routing is enabled for this surface. Defaults to
    ``True``. When routing is OFF, :meth:`RoutingState.get_target` returns
    ``None`` even if a target was previously set — the target is retained but
    suppressed, so flipping routing back on restores it.

This module holds no protocol models; the routing target is just the bare
``session_name`` string those models carry. Keep it dependency-light.
"""

from __future__ import annotations

import threading

# (user_id, endpoint, chat_id)
RoutingKey = tuple[str, str, str]


class RoutingState:
    """Per-surface routing-target state, held entirely in memory.

    A single instance is shared across the plugin's lifetime. The hook (gateway
    event-loop thread) mutates it while the outbound relay's background thread
    reads :meth:`active_targets`, so every access is guarded by a re-entrant lock
    — in particular ``active_targets`` snapshots under the lock so a concurrent
    ``set_target``/``clear_target`` cannot raise "dict changed size during
    iteration".
    """

    def __init__(self) -> None:
        self._targets: dict[RoutingKey, str] = {}
        # Routing defaults to ON; only keys explicitly turned off appear here.
        # Absent key == routing on.
        self._routing_off: set[RoutingKey] = set()
        self._lock = threading.RLock()

    @staticmethod
    def _key(user_id: str, endpoint: str, chat_id: str) -> RoutingKey:
        return (user_id, endpoint, chat_id)

    def set_target(
        self, user_id: str, endpoint: str, chat_id: str, session_name: str
    ) -> None:
        """Route this surface's messages to ``session_name``."""
        with self._lock:
            self._targets[self._key(user_id, endpoint, chat_id)] = session_name

    def get_target(self, user_id: str, endpoint: str, chat_id: str) -> str | None:
        """Return the routing target, or ``None`` if unset or routing is off.

        Routing being off suppresses resolution: the stored target (if any) is
        preserved but not returned until routing is turned back on.
        """
        key = self._key(user_id, endpoint, chat_id)
        with self._lock:
            if key in self._routing_off:
                return None
            return self._targets.get(key)

    def clear_target(self, user_id: str, endpoint: str, chat_id: str) -> None:
        """Remove this surface's routing target. No-op if none is set."""
        with self._lock:
            self._targets.pop(self._key(user_id, endpoint, chat_id), None)

    def set_routing(
        self, user_id: str, endpoint: str, chat_id: str, *, enabled: bool
    ) -> None:
        """Turn routing on or off for this surface (target is retained)."""
        key = self._key(user_id, endpoint, chat_id)
        with self._lock:
            if enabled:
                self._routing_off.discard(key)
            else:
                self._routing_off.add(key)

    def is_routing_on(self, user_id: str, endpoint: str, chat_id: str) -> bool:
        """Whether routing is currently enabled for this surface (default True)."""
        with self._lock:
            return self._key(user_id, endpoint, chat_id) not in self._routing_off

    def active_targets(self) -> set[str]:
        """Session names currently routable — a target is set AND routing is on.

        The outbound relay (U6) reconciles against this set: a session appears
        when its surface connects and disappears when it disconnects, so the relay
        consumes exactly the live targets' outbound streams without per-event
        wiring from the router.
        """
        with self._lock:
            return {
                target
                for key, target in self._targets.items()
                if key not in self._routing_off
            }
