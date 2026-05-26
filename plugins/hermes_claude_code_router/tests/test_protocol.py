"""Tests for the protocol pydantic models.

These mirror the tests in `redis-channel/tests/test_protocol.py`. Both repos
keep these in sync — if a test exists on one side and not the other, the
schemas have drifted and the next router/CC interaction will fail validation.
"""

from __future__ import annotations

import pytest
from hermes_claude_code_router.protocol import (
    PROTOCOL_VERSION,
    Inbound,
    LifecycleEvent,
    Outbound,
    PermissionRequest,
    PermissionVerdict,
    RegistryEntry,
    is_destructive,
)


def test_protocol_version_is_1() -> None:
    assert PROTOCOL_VERSION == 1


def test_inbound_minimal_voice() -> None:
    msg = Inbound(
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
    assert msg.v == 1
    assert msg.source == "voice"


def test_inbound_rejects_unknown_source() -> None:
    with pytest.raises(ValueError):
        Inbound(
            router="x",
            endpoint="y",
            source="telegram",  # type: ignore[arg-type]
            chat_id="c",
            user_id="u",
            username="n",
            text="hi",
            ts=0.0,
        )


def test_outbound_defaults_voice_false() -> None:
    msg = Outbound(
        session_name="s",
        endpoint="mimir",
        chat_id="c",
        text="hi",
        ts=0.0,
    )
    assert msg.voice is False


def test_registry_entry_serializes_capabilities() -> None:
    entry = RegistryEntry(
        session_name="s",
        host="h",
        cwd="/tmp",
        pid=1,
        started_at=0.0,
        capabilities=["reply", "permission"],
    )
    dumped = entry.model_dump()
    assert "permission" in dumped["capabilities"]


def test_permission_request_destructive_field() -> None:
    pr = PermissionRequest(
        session_name="s",
        endpoint="mimir",
        request_id="abcde",
        tool_name="Bash",
        input_preview="git push --force",
        destructive=True,
        originating_chat_id="c",
        ts=0.0,
    )
    assert pr.destructive is True
    assert len(pr.request_id) == 5


def test_permission_verdict_echo_outcome_default() -> None:
    pv = PermissionVerdict(
        session_name="s",
        endpoint="mimir",
        request_id="abcde",
        verdict="allow",
        source="voice",
        ts=0.0,
    )
    assert pv.echo_confirm_outcome == "not_required"


def test_lifecycle_event_minimal() -> None:
    ev = LifecycleEvent(type="registered", session_name="s", ts=0.0)
    assert ev.type == "registered"


# ─── is_destructive classifier ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "tool,inp,expected",
    [
        ("Write", "anything", True),
        ("Edit", "anything", True),
        ("NotebookEdit", "anything", True),
        ("Read", "anything", False),
        ("Glob", "anything", False),
        ("Bash", "ls -la", False),
        ("Bash", "git status", False),
        ("Bash", "rm -rf /tmp/foo", True),
        ("Bash", "rm -fr /tmp/foo", True),
        ("Bash", "git push --force", True),
        ("Bash", "git push -f origin main", True),
        ("Bash", "git reset --hard HEAD~3", True),
        ("Bash", "git clean -fd", True),
        ("Bash", "git branch -D feature/x", True),
        ("Bash", "psql -c 'DROP TABLE users;'", True),
        ("Bash", "psql -c 'drop table users'", True),
        ("Bash", "psql -c 'DELETE FROM users WHERE 1=1'", True),
        ("Bash", "psql -c 'TRUNCATE TABLE users'", True),
        ("Bash", "dd if=/dev/zero of=/dev/disk0", True),
    ],
)
def test_is_destructive(tool: str, inp: str, expected: bool) -> None:
    assert is_destructive(tool, inp) is expected
