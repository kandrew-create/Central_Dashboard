#!/usr/bin/env bash
set -euo pipefail
workspace="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd -- "$workspace"
uv_bin="${UV_BIN:-uv}"
if ! command -v "$uv_bin" >/dev/null 2>&1; then
  printf 'Install uv for Linux, or set UV_BIN to its executable path. See docs/wsl-deployment.md.\n' >&2
  exit 1
fi
if [[ ! -x .venv-gui/bin/python ]]; then
  "$uv_bin" venv --python 3.13 .venv-gui
fi
"$uv_bin" pip install --python .venv-gui/bin/python -r deploy/requirements.lock -e '.[docker-gui]'
.venv-gui/bin/python -c 'from PySide6.QtWidgets import QApplication; app=QApplication([])'
docker compose --project-name "${LINKER_COMPOSE_PROJECT:-linker-scada-wsl}" --env-file .env \
  -f deploy/docker-compose.yml -f deploy/docker-compose.wsl.yml build migrate
printf 'GUI installed. Launch with: bash deploy/wsl/launch-manager.sh\n'
