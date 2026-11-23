# hermes-claude-code-router

Hermes plugin that routes Discord voice and text messages to live **Claude Code sessions** via the `redis-channel` Claude Code channel plugin.

> **Status note.** `redis-channel`, the Claude Code half of this design, is retired (it was retired in `infiquetra-agent-plugins`) and its old home, `infiquetra-claude-plugins`, is archived. No replacement is named here, and the text below describes the original paired design.

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

This plugin and the retired `redis-channel` plugin shared a canonical wire-format spec, with a verbatim copy of `PROTOCOL.md` and `protocol.py` in both repos. With `redis-channel` retired, this repo's copy is the only one.

See [plugins/hermes_claude_code_router/PROTOCOL.md](plugins/hermes_claude_code_router/PROTOCOL.md) for the full specification.

State-machine semantics (state keys, transitions, race resolution) are documented in [docs/STATE_MACHINE.md](docs/STATE_MACHINE.md).

## Status

**Phase 0 scaffold.** Repo structure + protocol spec + state-machine spec + pydantic models pinning the wire format. Actual Hermes plugin hooks, Redis I/O, permission relay, and LLM tools land in later phases.

Roadmap and prerequisites lived in a companion plan in the now-archived `infiquetra/infiquetra-claude-plugins` (`.claude/plans/i-would-like-to-distributed-hanrahan.md`, private).

## Installation (when implemented)

```bash
git clone https://github.com/infiquetra/hermes-claude-code-router.git
cd hermes-claude-code-router
./scripts/install.sh plugin hermes_claude_code_router
```

Installs to `~/.hermes/plugins/hermes_claude_code_router/` and pip-installs `requirements.txt` into the Hermes venv. Mirror the pattern from [infiquetra-hermes-plugins](https://github.com/infiquetra/infiquetra-hermes-plugins).

After install, configure Mimir (or another Hermes profile) to load this plugin — see profile config example in the plan or in `plugins/hermes_claude_code_router/plugin.yaml`.

## Development

Agent guidance is centralized in `AGENTS.md`, which every supported coding CLI reads. `CLAUDE.md` is a one-line file (`@AGENTS.md`) that makes Claude Code import it.

```bash
uv sync
uv run pytest plugins/hermes_claude_code_router/tests/ -v
uv run ruff check plugins/
uv run mypy plugins/
```

## Related

- `redis-channel` — Claude Code channel plugin (CC side of this protocol). Retired; its old home, `infiquetra-claude-plugins`, is archived.
- `infiquetra-hermes-plugins` — pattern this repo was modeled on (private). Retired and archived.
- [Claude Code channels reference](https://code.claude.com/docs/en/channels-reference) — upstream channel protocol.

## License

MIT — see `LICENSE`.
