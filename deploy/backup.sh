#!/usr/bin/env bash
set -euo pipefail
umask 077
: "${AGE_RECIPIENT:?Set the off-server backup encryption recipient}"
: "${BACKUP_DIRECTORY:?Set a protected backup destination}"
mkdir -p "$BACKUP_DIRECTORY"
backup_file="$BACKUP_DIRECTORY/scada-$(date -u +%Y%m%dT%H%M%SZ).dump.age"
docker compose -f deploy/docker-compose.yml exec -T db \
  pg_dump -U scada_migrator -d scada_platform --format=custom \
  | age -r "$AGE_RECIPIENT" -o "$backup_file.partial"
mv "$backup_file.partial" "$backup_file"
sha256sum "$backup_file" > "$backup_file.sha256"
echo "Encrypted database backup created. Copy it and the checksum to the approved off-server destination."
