# Redis compatibility acceptance

The existing `test` CI job uses fakeredis and needs no Redis daemon. Its commands
and pytest discovery are unchanged. Run the ordinary suite with:

```bash
uv run pytest plugins/hermes_claude_code_router/tests/ -v
```

The separate **Redis compatibility** workflow checks the actual Redis Streams
interface on hosted ephemeral runners. It runs for PRs and main pushes changing
the router plugin, its compatibility workflow, `pyproject.toml`, or `uv.lock`;
published releases and manual dispatch also run it. Documentation-only changes
outside the plugin do not start this service.

The service uses the official Redis 7.4.12 image pinned to the immutable index
`redis:7-alpine@sha256:8da19c7399dca900c6822a1cf30f9d2285585e2c4b457ff4095b0f4500054d3f`.
GitHub assigns its host port; the acceptance client connects only to
`127.0.0.1` at that explicit port, with two-second socket timeouts and no retries.
The workflow bounds service readiness, the command (30 seconds), and the job
(five minutes).

To run acceptance locally, first create an owned ephemeral service from that
exact image and supply its published loopback port:

```bash
uv run python -m plugins.hermes_claude_code_router.compatibility.redis_roundtrip --port "$REDIS_TEST_PORT"
```

This command uses `RouterRedis` and the existing `Outbound` protocol model to
write a unique stream, read and validate its message through a consumer group,
verify pending state and acknowledgement, and delete the invocation's stream.
It fails when the configured service is unavailable. It never falls back to
fakeredis, reads a production Redis URL, or defaults to a local service. It is
outside ordinary pytest discovery, so unit collection remains unchanged.

Removing unused initialization from the unit job and adding real compatibility
assurance are separate compute changes. Historical combined container
initialization timings do not establish Redis savings or net workflow savings.
Qualify both hosted lanes on the submitted change before claiming acceptance.

Rollback: restore the `services.redis` block and pytest's `REDIS_HOST` /
`REDIS_PORT` environment in `.github/workflows/ci.yml` from the prior revision.
That rollback is independent of the compatibility workflow and command.
