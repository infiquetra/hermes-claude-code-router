"""hermes-claude-code-router — Hermes plugin that routes Discord text/voice to Claude Code sessions.

Phase 0 stub. The `register(ctx)` entry point is the documented Hermes plugin
hook (see hermes-extensions/docs/plugin-authoring.md). Actual hook + tool
registration arrives in Phase 1+.

See PROTOCOL.md (sibling file) for the Redis-streams wire format shared with
the companion redis-channel plugin.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__version__ = "0.1.0"


def register(ctx: Any) -> None:
    """Entry point called by Hermes at plugin load time.

    Will register (in later phases):
      - pre_gateway_dispatch hook for routing logic
      - LLM tools: list_cc_sessions, set_routing_target, get_routing_target
      - Lifecycle hooks for cleanup on session end
    """
    logger.info("hermes_claude_code_router v%s loaded (Phase 0 stub)", __version__)
    # ctx.register_hook("pre_gateway_dispatch", ...)  # Phase 1+
    # ctx.register_tool("list_cc_sessions", ...)       # Phase 5
    # ctx.register_tool("set_routing_target", ...)     # Phase 5
    # ctx.register_tool("get_routing_target", ...)     # Phase 5
