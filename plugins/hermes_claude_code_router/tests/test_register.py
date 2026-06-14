"""Tests for the U7 register(ctx) wiring (mock ctx; Redis deferred / fakeredis)."""

from __future__ import annotations

import time
from typing import Any

import fakeredis
import pytest

import hermes_claude_code_router as plugin
from hermes_claude_code_router.protocol import RegistryEntry
from hermes_claude_code_router.redis_client import ROUTER_GROUP, RouterRedis


class MockCtx:
    """Records register_hook / register_command calls."""

    def __init__(self) -> None:
        self.hooks: dict[str, Any] = {}
        self.commands: dict[str, Any] = {}
        self.hook_calls = 0
        self.command_calls: list[str] = []

    def register_hook(self, name: str, fn: Any) -> None:
        self.hook_calls += 1
        self.hooks[name] = fn

    def register_command(self, name: str, fn: Any, description: str = "") -> None:
        self.command_calls.append(name)
        self.commands[name] = fn


@pytest.fixture(autouse=True)
def _reset_plugin_state() -> Any:
    # Ensure each test starts from a clean module state.
    plugin._config.clear()
    plugin._redis = None
    plugin._relay = None
    yield


def test_register_wires_hook_and_commands_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    ctx = MockCtx()

    plugin.register(ctx)

    assert "pre_gateway_dispatch" in ctx.hooks
    assert ctx.hook_calls == 1
    assert {"/cc list", "/cc connect", "/cc disconnect", "/cc switch"} <= set(ctx.commands)
    # Each command registered exactly once.
    assert len(ctx.command_calls) == len(set(ctx.command_calls)) == 4


def test_missing_redis_url_raises_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    with pytest.raises(RuntimeError, match="REDIS_URL"):
        plugin.register(MockCtx())


def test_cc_list_formats_live_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    router = RouterRedis(fakeredis.FakeRedis(decode_responses=True), group=ROUTER_GROUP)
    entry = RegistryEntry(
        session_name="auth-feature",
        host="laptop.local",
        cwd="/Users/dev/workspace/auth-service",
        git_branch="feature/login",
        pid=4242,
        started_at=time.time(),
    )
    router.client.hset("cc-sessions:registry", "auth-feature", entry.model_dump_json())
    router.client.set("cc-sessions:hb:auth-feature", str(time.time()), ex=60)
    monkeypatch.setattr(plugin, "_get_redis", lambda: router)

    ctx = MockCtx()
    plugin.register(ctx)
    out = ctx.commands["/cc list"]()

    assert "auth-feature" in out
    assert "feature/login" in out
    assert "auth-service" in out  # cwd basename


def test_cc_list_empty_when_no_live_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    router = RouterRedis(fakeredis.FakeRedis(decode_responses=True), group=ROUTER_GROUP)
    monkeypatch.setattr(plugin, "_get_redis", lambda: router)

    ctx = MockCtx()
    plugin.register(ctx)
    assert ctx.commands["/cc list"]() == "No live Claude Code sessions."
