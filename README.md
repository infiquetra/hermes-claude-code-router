# hermes-claude-code-router

Hermes plugin that routes Discord voice and text messages to live **Claude Code sessions** via the [`redis-channel`](https://github.com/infiquetra/infiquetra-claude-plugins/tree/main/plugins/redis-channel) Claude Code channel plugin.

Together, they enable **hands-free interaction with a live Claude Code session** while driving, running, or working out: speak into Discord voice → Mimir's existing Hermes pipeline transcribes → router forwards to the connected CC session → response comes back as TTS in the same voice channel.

## How it fits

```
                            [User on phone]
                                  │ voice + text (Discord app)
                                  ▼
                          [Discord guild]
                                  │
                          [Hermes Mimir profile]
                                  │  existing pipeline (STT, LLM, TTS, playback)
                                  │  + this plugin (router)
                                  ▼
                          [Redis on Mac mini]
                                  │ streams: cc-sessions:<name>:inbound/outbound
                                  │ pub/sub: lifecycle events
                                  ▼
                  [redis-channel channel plugin (laptop)]
                                  │ stdio MCP
                                  ▼
                          [Claude Code session]
```

This plugin:
- Maintains routing-target state per `(user_id, endpoint, chat_id)` — when set, forwards inbound to the connected CC session instead of letting Mimir's LLM respond.
- Matches user phrases against slash/regex patterns to manage state (connect, disconnect, list, switch, start coding session, end coding session).
- Falls back to Mimir's LLM with registered tools (`list_cc_sessions`, `set_routing_target`, `get_routing_target`) for natural-language routing requests.
- Bridges Claude Code's permission requests (Bash, Write, etc.) over Discord with voice approval ("yes <id>" / "no <id>") and destructive echo-confirm.
- Reads the CC plugin's presence registry (`cc-sessions:registry` hash + `cc-sessions:hb:*` heartbeat keys) to surface live sessions.

## Protocol

This plugin and `redis-channel` share a canonical wire-format spec. Both repos keep a verbatim copy of `PROTOCOL.md` and `protocol.py`. Changes require synchronized PRs.

See [plugins/hermes_claude_code_router/PROTOCOL.md](plugins/hermes_claude_code_router/PROTOCOL.md) for the full specification.

State-machine semantics (state keys, transitions, race resolution) are documented in [docs/STATE_MACHINE.md](docs/STATE_MACHINE.md).

## Status

**Phase 0 scaffold.** Repo structure + protocol spec + state-machine spec + pydantic models pinning the wire format. Actual Hermes plugin hooks, Redis I/O, permission relay, and LLM tools land in later phases.

Roadmap and prerequisites live in the companion plan at `infiquetra/infiquetra-claude-plugins:.claude/plans/i-would-like-to-distributed-hanrahan.md` (private — DM @namredips if you need access).

## Installation (when implemented)

```bash
git clone https://github.com/infiquetra/hermes-claude-code-router.git
cd hermes-claude-code-router
./scripts/install.sh plugin hermes_claude_code_router
```

Installs to `~/.hermes/plugins/hermes_claude_code_router/` and pip-installs `requirements.txt` into the Hermes venv. Mirror the pattern from [infiquetra-hermes-plugins](https://github.com/infiquetra/infiquetra-hermes-plugins).

After install, configure Mimir (or another Hermes profile) to load this plugin — see profile config example in the plan or in `plugins/hermes_claude_code_router/plugin.yaml`.

## Development

Agent guidance is centralized in `AGENTS.md`. `CLAUDE.md`, `CODEX.md`, `GEMINI.md`, and `ANTIGRAVITY.md` are committed symlinks to that file so supported coding CLIs load the same repo instructions.

```bash
uv sync
uv run pytest plugins/hermes_claude_code_router/tests/ -v
uv run ruff check plugins/
uv run mypy plugins/
```

## Related

- [`redis-channel`](https://github.com/infiquetra/infiquetra-claude-plugins/tree/main/plugins/redis-channel) — Claude Code channel plugin (CC side of this protocol).
- [`infiquetra-hermes-plugins`](https://github.com/infiquetra/infiquetra-hermes-plugins) — pattern this repo was modeled on (private).
- [Claude Code channels reference](https://code.claude.com/docs/en/channels-reference) — upstream channel protocol.

## License

MIT — see `LICENSE`.
