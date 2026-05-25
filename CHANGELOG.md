# Changelog

All notable changes to `hermes-claude-code-router` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Initial repository scaffold modeled on [`hermes-extensions`](https://github.com/infiquetra/hermes-extensions).
- `scripts/install.sh` (copied verbatim from hermes-extensions) — installs plugins into `~/.hermes/plugins/`.
- `pyproject.toml` for dev tooling (uv-managed, dev deps include redis, pydantic, fakeredis for testing).
- `plugins/hermes_claude_code_router/PROTOCOL.md` — verbatim copy of the canonical protocol spec from the companion `redis-bridge` plugin in `infiquetra/infiquetra-claude-plugins`.
- `plugins/hermes_claude_code_router/protocol.py` — pydantic models matching the protocol, kept in sync with the CC side.
- `plugins/hermes_claude_code_router/plugin.yaml` — Hermes plugin manifest declaring the hook + tool registrations to come.
- `plugins/hermes_claude_code_router/__init__.py` — `register(ctx)` stub.
- `docs/STATE_MACHINE.md` — verbatim copy of the routing-target state machine spec.
- `plugins/hermes_claude_code_router/tests/test_protocol.py` — mirror of the CC-side protocol tests; ensures the two pydantic copies stay structurally identical.
- `.github/workflows/ci.yml` — runs pytest + ruff + mypy on PRs.

### Not implemented yet (planned)

- `router.py` — main message classification + dispatch logic
- `matchers.py` — slash/regex patterns
- `state.py` — routing-target state machine persistence
- `redis_client.py` — XADD/XREADGROUP/PUBSUB plumbing
- `permission.py` — TTS prompt composition + STT yes/no listener + destructive echo-confirm
- `llm_tools.py` — `list_cc_sessions`, `set_routing_target`, `get_routing_target` exposed to Mimir LLM via `ctx.register_tool`
- `registry_reader.py` — read `cc-sessions:registry` with hb-key filter
