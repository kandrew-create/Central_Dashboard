#!/usr/bin/env bash
set -euo pipefail
umask 077
: "${SCADA_RESTORE_CONFIRMED:?Set only for an authorized restoration on a clean recovery host}"
: "${AGE_IDENTITY:?Set the protected backup decryption identity path}"
if [ "$SCADA_RESTORE_CONFIRMED" != 'clean-recovery-host' ]; then
  echo 'Refusing restore without explicit clean recovery host confirmation.' >&2
  exit 1
fi
backup_file="${1:?Supply an encrypted backup file}"
sha256sum -c "$backup_file.sha256"
docker compose -f deploy/docker-compose.yml stop api worker
# Initialize/migrate the recovery database and bootstrap NOLOGIN roles before
# restoring. This deliberately replaces objects only on the confirmed host.
age -d -i "$AGE_IDENTITY" "$backup_file" \
  | docker compose -f deploy/docker-compose.yml exec -T db \
      pg_restore -U scada_migrator -d scada_platform --clean --if-exists --exit-on-error
echo 'Restore finished. Verify data, credentials, leases and replay/retention assumptions before starting API/worker.'
