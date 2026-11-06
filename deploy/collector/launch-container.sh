#!/usr/bin/env bash
set -euo pipefail
workspace="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$workspace"
# No inherited remote engine, alternative Compose project, or TLS routing.
while IFS= read -r variable; do
    case "$variable" in DOCKER_*|COMPOSE_*) unset "$variable" ;; esac
done < <(compgen -e)
if [[ ! -S /tmp/.X11-unix/X0 ]]; then
    echo 'WSLg is unavailable. Start the existing WSL GUI environment and retry.' >&2
    exit 1
fi
docker=(docker --host unix:///var/run/docker.sock)
[[ "$("${docker[@]}" info --format '{{.OSType}}')" == linux ]]
export COLLECTOR_DOCKER_GID="$(stat -c %g /var/run/docker.sock)"
for volume in linker-collector_collector-data linker-collector_collector-key; do
    "${docker[@]}" volume inspect "$volume" >/dev/null
done
# No initialization, key creation, source access or automatic scheduler startup.
export COLLECTOR_HANDOFF_DIR="$workspace/collector-handoff"
mkdir -p "$COLLECTOR_HANDOFF_DIR"
compose=(compose --project-name linker-collector
    -f deploy/docker-compose.collector.yml
    -f deploy/docker-compose.collector.host.yml
    -f deploy/docker-compose.collector.desktop.yml)
"${docker[@]}" "${compose[@]}" up -d --no-deps --pull never desktop
