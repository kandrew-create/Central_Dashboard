"""Desktop operations shared with the CLI; no GUI or database work at import time."""
from dataclasses import replace
import json
import tomllib

from collector import secrets
from collector.config import EXAMPLE, PROFILE, load_config, parse_config
from collector.errors import CollectorError
from collector.source import SourceReader

EDITABLE_FIELDS = ("host", "port", "database", "user", "sslmode", "timezone",
                   "schema", "alarm_table", "event_table", "source_id", "generation_id", "collection_enabled",
                   "marker_verified", "scan_mode", "history_start", "history_end", "all_history", "page_rows", "max_pages",
                   "overlap_seconds", "reconcile_ids", "queue_bytes", "min_free_bytes", "privacy", "upload_url", "upload_enabled",
                   "interval_seconds", "schedule_mode", "schedule_timezone", "schedule_time", "schedule_weekday", "upload_ca_file")

COLLECTION_FIELDS = EDITABLE_FIELDS[9:24]
UPLOAD_FIELDS = ('upload_url', 'upload_enabled', 'upload_ca_file')
SCHEDULE_FIELDS = ('interval_seconds', 'schedule_mode', 'schedule_timezone', 'schedule_time', 'schedule_weekday')


def default_config(path):
    return parse_config(tomllib.loads(EXAMPLE), path)


def config_document(config):
    return {
        "version": 1,
        "database": {"host": config.host, "port": config.port, "name": config.database,
                     "user": config.user, "sslmode": config.sslmode,
                     "connect_timeout_seconds": config.connect_timeout_seconds,
                     "statement_timeout_ms": config.statement_timeout_ms,
                     "lock_timeout_ms": config.lock_timeout_ms},
        "source": {"profile": PROFILE, "schema": config.schema, "alarm_table": config.alarm_table,
                   "event_table": config.event_table, "timezone": config.timezone},
        "limits": {"preview_rows": config.preview_rows, "max_field_bytes": config.max_field_bytes,
                   "max_output_bytes": config.max_output_bytes},
        "collection": {name: getattr(config, name) for name in COLLECTION_FIELDS},
        "upload": {name: getattr(config, name) for name in UPLOAD_FIELDS},
        "schedule": {name: getattr(config, name) for name in SCHEDULE_FIELDS},
    }


def serialize_config(config):
    document = config_document(config)
    lines = ["# SCADA Collector local settings. Passwords are stored separately with Windows protection.",
             "version = 1", ""]
    for section in document:
        if section == 'version':
            continue
        lines.append(f"[{section}]")
        for key, value in document[section].items():
            lines.append(f"{key} = {json.dumps(value, ensure_ascii=False)}")
        lines.append("")
    return "\n".join(lines)


def form_config(base, fields):
    if set(fields) != set(EDITABLE_FIELDS):
        raise CollectorError("The settings form is incomplete; reopen the setup window.")
    values = dict(fields)
    if not all(isinstance(value, str) for value in values.values()):
        raise CollectorError("Settings must be entered as text.")
    try:
        for name, value in values.items():
            original = getattr(base, name)
            if type(original) is int:
                values[name] = int(value.strip())
            elif type(original) is bool:
                if value.lower() not in {'true', 'false'}:
                    raise ValueError()
                values[name] = value.lower() == 'true'
    except ValueError:
        raise CollectorError("Enter whole numbers for limits/ports and True or False for enabled settings.") from None
    candidate = replace(base, **values)
    return parse_config(config_document(candidate), candidate.path)


def require_current(config):
    if load_config(config.path) != config:
        raise CollectorError("Settings changed outside this window. Reopen the settings file before continuing.")


class DesktopService:
    def check_upload(self, config):
        require_current(config)
        from collector.connection import check_upload
        return check_upload(config)

    def import_setup(self, config, path, password):
        from collector.setup_import import import_setup
        return import_setup(self, config, path, password)

    def cycle(self, config):
        require_current(config)
        from collector.runtime import cycle
        return cycle(config)

    def status(self, config):
        require_current(config)
        from collector.runtime import status
        return status(config)

    def store_upload_token(self, config, token):
        require_current(config)
        if not isinstance(token,str) or not token.isascii() or not 43 <= len(token) <= 256:
            raise CollectorError('Enter the server-provisioned upload credential (43-256 ASCII characters).')
        secrets.save_password(config.upload_password_path, token)

    def load(self, path):
        return load_config(path)

    def save(self, config, previous=None):
        content = serialize_config(config)
        # Validate the exact serialized document before writing it.
        parse_config(tomllib.loads(content), config.path)
        if previous is None:
            if config.path.exists():
                raise CollectorError("This settings file already exists. Open it before making changes.")
            secrets.initialize(config.path, content)
        else:
            if previous.path != config.path:
                raise CollectorError("Create a new setup to save in a different location.")
            require_current(previous)
            if config.path.is_symlink():
                raise CollectorError("Settings files must not be symbolic links.")
            secrets.write_private_file(config.path, content.encode("utf-8"))
        return load_config(config.path)

    def store_password(self, config, password):
        require_current(config)
        secrets.save_password(config.password_path, password)

    def check(self, config):
        require_current(config)
        return self._reader(config).check()

    def preview(self, config, table, limit, after_id=None, include_user_fields=False):
        require_current(config)
        return self._reader(config).preview(
            table, after_id=after_id, limit=limit, include_user_fields=include_user_fields)

    @staticmethod
    def _reader(config):
        try:
            password = secrets.load_password(config.password_path)
        except CollectorError:
            raise CollectorError("Cannot unlock the saved password. Store it again using the collector's Windows account.") from None
        return SourceReader(config, password)


def table_values(record):
    """A readable summary; original values and uncertainty remain in record details."""
    row = record["original"]
    alarm = record["record_type"] == "alarm"
    names = ("al_event_time", "al_start_time", "last_update") if alarm else ("ev_time", "last_update")
    stamp = next((record["times"][name] for name in names if record["times"][name]["local"] is not None), None)
    when = (stamp["local"].replace("T", " ") if stamp else "Unknown")
    flag = lambda value: "Yes" if value is True else "No" if value is False else "Unknown"
    value = row.get("al_tag_value" if alarm else "ev_value")
    return (record["source_record_id"], when, row.get("al_tag" if alarm else "ev_source") or "—",
            row.get("al_message" if alarm else "ev_message") or "—", "—" if value is None else value,
            flag(row.get("al_active")) if alarm else "—", flag(row.get("al_ack")) if alarm else "—",
            stamp["quality"].replace("_", " ").capitalize() if stamp else "Missing")
