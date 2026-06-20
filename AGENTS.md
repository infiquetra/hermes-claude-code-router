# Agent configuration for `hermes-claude-code-router`

This file is the canonical guidance for agentic coding CLIs in this repository. Tool-specific entrypoints (`CLAUDE.md`, `CODEX.md`, `GEMINI.md`, and `ANTIGRAVITY.md`) are symlinks to this file so every supported CLI sees the same repo instructions. It points at the canonical context for working in this repo and lays out the engineering-journal maintenance rules. **Read the journal first if you're picking up a new session in this repo.**

## Engineering journal (canonical context)

Living documentation at [`docs/engineering-journal/`](docs/engineering-journal/) — pattern adopted from `infiquetra/infiquetra-claude-plugins/docs/engineering-journal/` (which itself adopted from `infiquetra/home-lab/docs/engineering-journal/`).

| File | Purpose |
|------|---------|
| [LEARNINGS.md](docs/engineering-journal/LEARNINGS.md) | Empirical findings + mechanisms + fixes + validations |
| [DECISIONS.md](docs/engineering-journal/DECISIONS.md) | ADR-style records of pattern / convention / tooling choices |
| [QUEUED.md](docs/engineering-journal/QUEUED.md) | Future-work items by priority with "worth it when" triggers |
| [ARCHIVE.md](docs/engineering-journal/ARCHIVE.md) | Shipped + rejected + superseded items |
| [narratives/](docs/engineering-journal/narratives/) | Self-contained, longer-form companion docs |

**The current state of this repo is v1 human-relay spine shipped** (Phase A; PR #6, merged 2026-06-14; 118 tests pass, ruff + mypy clean). v1 text routing is live. The next implementation session should start by reading [`docs/work-sessions/2026-06-14-v1-spine.md`](docs/work-sessions/2026-06-14-v1-spine.md) for what shipped and [`docs/engineering-journal/QUEUED.md`](docs/engineering-journal/QUEUED.md) for the Phase 4+ priorities (voice transcript routing, voice-forge TTS). The original build plan at [`docs/engineering-journal/narratives/2026-05-26-router-build-plan.md`](docs/engineering-journal/narratives/2026-05-26-router-build-plan.md) is retained as historical context for Phases 4-6 intent.

## Maintenance rules (agents: follow these without being asked)

1. **After fixing a bug or shipping a feature where the mechanism wasn't obvious** → add a dated entry to `LEARNINGS.md`. Include **evidence** (PR/commit/file:line) and **mechanism** (why it happened, not just what), and a **Generalizable rule** line.

2. **After committing a pattern/convention decision** → add to `DECISIONS.md` with rationale + rejected alternatives + "revisit when" condition. Include the commit hash.

3. **Whenever a promising idea surfaces but we don't build it right now** → `QUEUED.md` with priority (P0/P1/P2/P3/Maybe), concrete "worth it when" trigger, rough effort estimate.

4. **When a QUEUED item ships** → move to `ARCHIVE.md` as SHIPPED with commit hash + date.

5. **When a QUEUED item is rejected** → move to `ARCHIVE.md` as REJECTED with reason + revisit conditions.

6. **When a prior LEARNING or DECISION is invalidated** → update inline AND move pre-correction version to `ARCHIVE.md` as SUPERSEDED. Never silently overwrite history.

7. **When something needs a longer write-up than fits an entry** → create `docs/engineering-journal/narratives/YYYY-MM-DD-short-slug.md`.

**Don't wait to be asked.** When any of these triggers fire, update the files as part of the same commit.

## Cross-repo cohort

This repo is the **router side** of a paired build with [`infiquetra/infiquetra-claude-plugins`](https://github.com/infiquetra/infiquetra-claude-plugins) (CC-plugin side, specifically `plugins/redis-channel/`). They share the canonical wire-format spec ([`PROTOCOL.md`](plugins/hermes_claude_code_router/PROTOCOL.md)) and Pydantic models ([`protocol.py`](plugins/hermes_claude_code_router/protocol.py)). Per [DECISIONS#protocol-py-byte-identical](docs/engineering-journal/DECISIONS.md#protocol-py-byte-identical): keep both in sync byte-identical; protocol changes require synchronized PRs.

**Important cross-repo references:**
- [`infiquetra-claude-plugins/plugins/redis-channel/PROTOCOL.md`](https://github.com/infiquetra/infiquetra-claude-plugins/blob/main/plugins/redis-channel/PROTOCOL.md) — the canonical wire format
- [`infiquetra-claude-plugins/plugins/redis-channel/docs/STATE_MACHINE.md`](https://github.com/infiquetra/infiquetra-claude-plugins/blob/main/plugins/redis-channel/docs/STATE_MACHINE.md) — router-side state machine spec
- [`infiquetra-claude-plugins/docs/engineering-journal/LEARNINGS.md`](https://github.com/infiquetra/infiquetra-claude-plugins/blob/main/docs/engineering-journal/LEARNINGS.md) — especially `#cc-channels-bg-not-supported` (affects Phase 5 spawn design) and `#cc-channels-surface-split` (don't try to mirror terminal/channel)
- Master plan: `~/.claude/plans/i-would-like-to-distributed-hanrahan.md` — historical artifact, still load-bearing for Phases 4-6 intent

## Where Hermes runs

Hermes runs on `jeffs-mac-mini.infiquetra.com` (not the dev laptop). The Mimir profile config lives in `~/workspace/infiquetra/home-lab/ansible/inventory/host_vars/jeffs-mac-mini.infiquetra.com.yml` and is Ansible-templated. Mimir's profile name is `mimir-engineer` (not `mimir`); his voice channel is Mímisbrunnr (`1508449251472969950`). See [LEARNINGS#mimir-profile-config-location](docs/engineering-journal/LEARNINGS.md#mimir-profile-config-location).

For development: install this plugin via `./scripts/install.sh plugin hermes_claude_code_router` which copies into `~/.hermes/plugins/`. The Hermes daemon picks it up on restart. For production: `git pull && ./scripts/install.sh ...` on the Mac mini, then bounce Hermes.

## Coding standards

- Python 3.12+; type hints; Pydantic v2.
- Pre-commit + ruff lint + mypy strict (where deps allow).
- Tests: pytest. Plugin tests live at `plugins/hermes_claude_code_router/tests/`.
- Follow `infiquetra-hermes-plugins/plugins/security_guidance/` file layout (simplest existing real plugin).

## Commands

```bash
uv run pytest plugins/hermes_claude_code_router/tests/ -v   # run the test suite
uv run ruff check plugins/                                  # lint
uv run mypy plugins/                                        # type-check
./scripts/install.sh plugin hermes_claude_code_router       # install into ~/.hermes/plugins/
```

## Communication preferences

- Concise > verbose.
- Code-first explanations.
- Verify before asserting (run the test, query the state — don't guess).
- If unsure about Hermes internals, read the docs at https://hermes-agent.nousresearch.com/docs/ or the upstream source in NousResearch/hermes-agent rather than guessing.
