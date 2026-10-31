#!/usr/bin/env bash
set -euo pipefail
workspace="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
interpreter="$workspace/.venv-gui/bin/python"
if [[ ! -x "$interpreter" ]]; then
  printf 'Install the WSL GUI environment first; see docs/wsl-deployment.md.\n' >&2
  exit 1
fi
exec "$interpreter" -m server.management.qt_docker_gui --workspace "$workspace" "$@"
