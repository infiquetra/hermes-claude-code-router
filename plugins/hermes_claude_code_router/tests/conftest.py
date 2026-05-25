"""Shared pytest fixtures for hermes-claude-code-router tests."""

from __future__ import annotations

import sys
from pathlib import Path

# Make the plugin package importable from tests.
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT))
