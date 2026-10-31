"""One local Docker command per request; never a network administration service."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import UUID

from cryptography import x509
import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from collector.errors import CollectorError
from server.management.linux_vault import LinuxVault, private_directory, private_write
from server.management.service import ManagerService, text


ACTIONS = frozenset(('counts', 'catalog', 'sources', 'register', 'delete_source', 'rotate',
                     'export', 'batches', 'machine_interpretations'))


class DockerAgent(ManagerService):
    def __init__(self, state=Path('/manager-state'), ca=Path('/manager-ca.pem'), connection_factory=None):
        port = int(os.environ.get('LINKER_MANAGER_HTTPS_PORT', '443'))
        if not 1 <= port <= 65535:
            raise CollectorError('Invalid local HTTPS port for this Docker manager.')
        self.settings = SimpleNamespace(data_dir=Path(state), mode='local', server_host='localhost',
                                        upload_url='https://localhost' + (':' + str(port) if port != 443 else '') + '/v1/uploads')
        self.ca = Path(ca)
        self.connection_factory = connection_factory
        self.vault = LinuxVault(state)

    @contextmanager
    def connection(self):
        if self.connection_factory:
            with self.connection_factory() as db:
                yield db
            return
        url = os.environ['MIGRATION_DATABASE_URL'].replace('postgresql+psycopg://', 'postgresql://', 1)
        info = conninfo_to_dict(url)
        if (info.get('host'), info.get('dbname'), info.get('user')) != ('db', 'scada_platform', 'scada_migrator'):
            raise CollectorError('Docker management requires this project\'s Central database service and migration identity.')
        with psycopg.connect(url, row_factory=dict_row, connect_timeout=5,
                             options='-c statement_timeout=5000 -c lock_timeout=2000') as db:
            if not db.execute("SELECT to_regclass('platform.source_storage') storage").fetchone()['storage']:
                raise CollectorError('Initialize the Central Server schema before opening the Docker manager.')
            yield db

    def _vault_path(self, source_id):
        return private_directory(self.settings.data_dir) / (str(UUID(str(source_id))) + '.vault')

    def _store(self, setup):
        self.vault.save(self._vault_path(setup['source_id']), setup)

    def _load_setup(self, path):
        return self.vault.load(path)

    def _restore_vault(self, path, content):
        private_write(path, content)

    def _protect_export(self, path):
        os.chmod(path, 0o600)

    def _validate_export(self):
        certificate = x509.load_pem_x509_certificate(self.ca.read_bytes())
        now = datetime.now(timezone.utc)
        if (not certificate.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
                or not certificate.not_valid_before_utc <= now < certificate.not_valid_after_utc):
            raise CollectorError('Refresh the Docker server CA certificate before exporting a setup.')

    def _export_ca(self):
        return self.ca.read_text(encoding='ascii')

    def register(self, source_name, customer_name='', site_name='', project_name='', machine_tag='',
                 customer_id=None, site_id=None, project_id=None, machine_id=None):
        values = dict(source_name=text(source_name, 'SCADA PC/source name'),
                      customer_name=customer_name, site_name=site_name, project_name=project_name, machine_tag=machine_tag,
                      customer_id=customer_id, site_id=site_id, project_id=project_id, machine_id=machine_id)
        for identifier, name, label in (('customer_id', 'customer_name', 'customer name'),
                                        ('site_id', 'site_name', 'site name'),
                                        ('project_id', 'project_name', 'project name'),
                                        ('machine_id', 'machine_tag', 'machine tag')):
            if not values[identifier]:
                values[name] = text(values[name], label)
        return super().register(**values)

    def counts(self):
        with self.connection() as db:
            return db.execute('''SELECT (SELECT count(*) FROM platform.sources WHERE deleted_at IS NULL) sources,
                (SELECT count(*) FROM platform.upload_batches) batches,
                (SELECT count(*) FROM platform.alarm_event_revisions) revisions,
                (SELECT count(*) FROM platform.upload_batches WHERE processing_status='quarantined') quarantined_batches,
                (SELECT count(*) FROM platform.jobs WHERE status='failed') failed_jobs''').fetchone()

    def machine_interpretations(self, include_records=True):
        result = dict(configuration=dict(enabled=False, model='Not configured in Docker'),
                      rows=[], records_available=include_records)
        if include_records:
            with self.connection() as db:
                result['rows'] = db.execute('''SELECT i.source_record_id,i.source_table,i.status,i.candidates,
                    i.model,i.policy_version,s.name source_name,r.message original_message
                    FROM platform.machine_interpretations i JOIN platform.sources s USING(source_id)
                    JOIN platform.alarm_event_revisions r ON r.revision_id=i.revision_id
                    ORDER BY i.interpreted_at DESC NULLS LAST,i.revision_id LIMIT 200''').fetchall()
        return result


def main():
    try:
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            raise ValueError()
        request = json.loads(raw)
        if (not isinstance(request, dict) or set(request) != {'action', 'arguments'}
                or request['action'] not in ACTIONS or not isinstance(request['arguments'], dict)):
            raise ValueError()
        if request['action'] == 'export':
            target = Path(request['arguments']['path'])
            if target.parent != Path('/exports') or target.name in ('', '.', '..'):
                raise ValueError()
        result = getattr(DockerAgent(), request['action'])(**request['arguments'])
        response = dict(ok=True, result=result)
    except CollectorError as error:
        response = dict(ok=False, error=str(error))
    except Exception:
        response = dict(ok=False, error='Docker management failed. Check the selected project, database and private credential directory.')
    sys.stdout.write(json.dumps(response, default=str))
    return 0 if response['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
