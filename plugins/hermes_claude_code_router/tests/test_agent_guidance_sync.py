from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CANONICAL_GUIDANCE = REPO_ROOT / "AGENTS.md"
TOOL_GUIDANCE_FILES = [
    "CLAUDE.md",
    "CODEX.md",
    "GEMINI.md",
    "ANTIGRAVITY.md",
]
REQUIRED_CONTEXT_REFERENCES = [
    "docs/engineering-journal/",
    "docs/engineering-journal/narratives/2026-05-26-router-build-plan.md",
    "plugins/hermes_claude_code_router/PROTOCOL.md",
    "plugins/hermes_claude_code_router/protocol.py",
]


def test_tool_guidance_files_are_symlinks_to_agents_md() -> None:
    for filename in TOOL_GUIDANCE_FILES:
        path = REPO_ROOT / filename

        assert path.is_symlink(), f"{filename} must be a symlink to AGENTS.md"
        assert os.readlink(path) == "AGENTS.md"
        assert path.read_bytes() == CANONICAL_GUIDANCE.read_bytes()


def test_agents_md_keeps_required_repo_context() -> None:
    guidance = CANONICAL_GUIDANCE.read_text(encoding="utf-8")

    for reference in REQUIRED_CONTEXT_REFERENCES:
        assert reference in guidance
