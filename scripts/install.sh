#!/usr/bin/env bash
# Install Hermes plugins and MCP servers from this repository.
#
# Skills use Hermes's native installer (see README). This script only
# handles plugins and MCP servers, which Hermes does not install natively.
#
# Usage:
#   scripts/install.sh plugin <name> [--hermes-home DIR] [--force]
#   scripts/install.sh mcp    <name> [--hermes-home DIR] [--force]
#   scripts/install.sh list
#   scripts/install.sh --help
#
# Environment:
#   HERMES_HOME   Override the Hermes home dir (default: ~/.hermes)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
FORCE=0

die() { echo "error: $*" >&2; exit 1; }
info() { echo "==> $*"; }
warn() { echo "warn: $*" >&2; }

usage() {
  sed -n '2,16p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

list_units() {
  echo "plugins:"
  local any=0
  for d in "$REPO_ROOT"/plugins/*/; do
    [ -d "$d" ] || continue
    echo "  - $(basename "$d")"
    any=1
  done
  [ "$any" -eq 0 ] && echo "  (none)"

  echo "mcp servers:"
  any=0
  for d in "$REPO_ROOT"/mcp/*/; do
    [ -d "$d" ] || continue
    echo "  - $(basename "$d")"
    any=1
  done
  [ "$any" -eq 0 ] && echo "  (none)"
}

install_plugin() {
  local name="$1"
  local src="$REPO_ROOT/plugins/$name"
  local dest="$HERMES_HOME/plugins/$name"

  [ -d "$src" ] || die "plugin '$name' not found under plugins/"
  [ -f "$src/__init__.py" ] || die "plugin '$name' missing __init__.py"
  [ -f "$src/plugin.yaml" ] || die "plugin '$name' missing plugin.yaml"

  if [ -e "$dest" ] && [ "$FORCE" -eq 0 ]; then
    info "$dest already exists; use --force to overwrite"
    return 0
  fi

  info "installing plugin '$name' -> $dest"
  mkdir -p "$(dirname "$dest")"
  rm -rf "$dest"
  cp -R "$src" "$dest"

  if [ -s "$src/requirements.txt" ]; then
    local venv_python="$HERMES_HOME/hermes-agent/venv/bin/python"
    if [ -x "$venv_python" ]; then
      info "installing plugin deps into Hermes venv"
      "$venv_python" -m pip install --disable-pip-version-check \
          -r "$src/requirements.txt"
    else
      warn "Hermes venv not found at $venv_python; skipping pip install"
      warn "run manually: pip install -r $src/requirements.txt"
    fi
  fi

  info "plugin '$name' installed"
}

install_mcp() {
  local name="$1"
  local src="$REPO_ROOT/mcp/$name"
  local dest="$HERMES_HOME/mcp-servers/$name"

  [ -d "$src" ] || die "mcp server '$name' not found under mcp/"
  [ -f "$src/server.py" ] || die "mcp server '$name' missing server.py"
  [ -f "$src/manifest.yaml" ] || die "mcp server '$name' missing manifest.yaml"

  if [ -e "$dest" ] && [ "$FORCE" -eq 0 ]; then
    info "$dest already exists; use --force to overwrite"
    return 0
  fi

  info "installing mcp server '$name' -> $dest"
  mkdir -p "$(dirname "$dest")"
  rm -rf "$dest"
  cp -R "$src" "$dest"

  if [ -f "$src/pyproject.toml" ]; then
    info "creating isolated venv at $dest/.venv"
    python3 -m venv "$dest/.venv"
    "$dest/.venv/bin/pip" install --disable-pip-version-check --upgrade pip >/dev/null
    "$dest/.venv/bin/pip" install --disable-pip-version-check "$dest"
  fi

  info "mcp server '$name' installed"
  info "append the snippet from $dest/manifest.yaml to ~/.hermes/config.yaml under 'mcp_servers:'"
}

main() {
  [ $# -ge 1 ] || { usage; exit 2; }

  case "$1" in
    -h|--help) usage; exit 0 ;;
    list)      list_units; exit 0 ;;
    plugin|mcp) ;;
    *) die "unknown command: $1" ;;
  esac

  local kind="$1"; shift
  [ $# -ge 1 ] || die "$kind requires a name argument"
  local name="$1"; shift

  while [ $# -gt 0 ]; do
    case "$1" in
      --hermes-home) HERMES_HOME="$2"; shift 2 ;;
      --force)       FORCE=1; shift ;;
      *) die "unknown option: $1" ;;
    esac
  done

  case "$kind" in
    plugin) install_plugin "$name" ;;
    mcp)    install_mcp "$name" ;;
  esac
}

main "$@"
