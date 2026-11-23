from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CANONICAL_GUIDANCE = REPO_ROOT / "AGENTS.md"
RETIRED_GUIDANCE_FILES = [
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


def test_claude_md_imports_agents_md() -> None:
    # AGENTS.md is the single instruction file. CLAUDE.md is a regular one-line
    # file that makes Claude Code import it (infiquetra-context-library
    # docs/ai-context/instruction-surfaces.md).
    path = REPO_ROOT / "CLAUDE.md"

    assert not path.is_symlink(), "CLAUDE.md must be a regular file, not a symlink"
    assert path.read_text(encoding="utf-8") == "@AGENTS.md\n"


def test_retired_tool_guidance_files_are_absent() -> None:
    for filename in RETIRED_GUIDANCE_FILES:
        path = REPO_ROOT / filename

        assert not path.exists() and not path.is_symlink(), f"{filename} is retired; AGENTS.md is read directly"


def test_agents_md_keeps_required_repo_context() -> None:
    guidance = CANONICAL_GUIDANCE.read_text(encoding="utf-8")

    for reference in REQUIRED_CONTEXT_REFERENCES:
        assert reference in guidance
