"""Strict local configuration for the first collector commissioning increment."""
from dataclasses import dataclass, fields
from pathlib import Path
import re
import tomllib
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from urllib.parse import urlsplit
from uuid import UUID

from collector.errors import CollectorError

PROFILE = "ecostruxure_machine_scada_expert_v1"
TABLES = ("alarmhistory", "eventhistory")
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}\Z")

EXAMPLE = '''# Collection and uploads remain disabled until explicitly configured locally.
version = 1

[database]
host = "localhost"
port = 5432
name = "scada"
user = "scada_collector"
# disable is permitted only for loopback. Use verify-full for a remote host.
sslmode = "disable"
connect_timeout_seconds = 5
statement_timeout_ms = 5000
lock_timeout_ms = 1000

[source]
profile = "ecostruxure_machine_scada_expert_v1"
schema = "public"
alarm_table = "alarmhistory"
event_table = "eventhistory"
# Set the actual source IANA timezone, for example America/Toronto.
# Empty preserves local timestamps without guessing UTC.
timezone = ""

[limits]
preview_rows = 20
max_field_bytes = 4096
max_output_bytes = 262144

[collection]
source_id = ""
generation_id = ""
collection_enabled = false
marker_verified = false
scan_mode = "id_range"
history_start = ""
history_end = ""
all_history = false
page_rows = 50
max_pages = 10
overlap_seconds = 600
reconcile_ids = 10000
queue_bytes = 268435456
min_free_bytes = 104857600
privacy = "upload_all"

[upload]
upload_url = ""
upload_enabled = false
upload_ca_file = ""

[schedule]
interval_seconds = 60
schedule_mode = "interval"
schedule_timezone = "UTC"
schedule_time = "02:00"
schedule_weekday = 0
'''


def _integer(section, name, default, lower, upper):
    value = section.get(name, default)
    if type(value) is not int or not lower <= value <= upper:
        raise CollectorError(f"{name} must be an integer from {lower} to {upper}.")
    return value


def _text(section, name, default=None):
    value = section.get(name, default)
    if not isinstance(value, str) or not value or len(value) > 255 or any(ord(c) < 32 for c in value):
        raise CollectorError(f"{name} must be nonempty text of at most 255 characters.")
    return value


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise CollectorError("Schema/table identifiers must use 1-63 ASCII letters, digits, or underscores.")
    if value.casefold() == "heartbeat":
        raise CollectorError("Heartbeat is outside the approved source profile.")
    return value


@dataclass(frozen=True)
class CollectorConfig:
    path: Path
    host: str
    port: int
    database: str
    user: str
    sslmode: str
    connect_timeout_seconds: int
    statement_timeout_ms: int
    lock_timeout_ms: int
    schema: str
    alarm_table: str
    event_table: str
    timezone: str
    preview_rows: int
    max_field_bytes: int
    max_output_bytes: int
    source_id: str = ""
    generation_id: str = ""
    collection_enabled: bool = False
    marker_verified: bool = False
    scan_mode: str = "id_range"
    history_start: str = ""
    history_end: str = ""
    all_history: bool = False
    page_rows: int = 50
    max_pages: int = 10
    overlap_seconds: int = 600
    reconcile_ids: int = 10000
    queue_bytes: int = 268435456
    min_free_bytes: int = 104857600
    privacy: str = "upload_all"
    upload_url: str = ""
    upload_enabled: bool = False
    upload_ca_file: str = ""
    interval_seconds: int = 60
    schedule_mode: str = "interval"
    schedule_timezone: str = "UTC"
    schedule_time: str = "02:00"
    schedule_weekday: int = 0

    @property
    def state_path(self):
        return self.path.parent / "state" / "collector.sqlite3"

    @property
    def upload_password_path(self):
        return self.path.parent / "secrets" / "upload-token.dpapi"

    @property
    def privacy_key_path(self):
        return self.path.parent / "secrets" / "privacy-key.dpapi"

    @property
    def password_path(self):
        return self.path.parent / "secrets" / "database-password.dpapi"

    def table(self, logical_name):
        if logical_name not in TABLES:
            raise CollectorError("Only alarmhistory and eventhistory are approved.")
        return self.alarm_table if logical_name == "alarmhistory" else self.event_table


def load_config(path):
    path = Path(path).resolve()
    try:
        if path.stat().st_size > 16384:
            raise CollectorError("Configuration exceeds 16 KiB.")
        with path.open("rb") as stream:
            data = tomllib.load(stream)
    except (OSError, ValueError):
        raise CollectorError("Cannot read configuration; check its path and TOML syntax.") from None
    return parse_config(data, path)


def parse_config(data, path):
    """Validate the same contract for file and desktop-form input."""
    path = Path(path).resolve()
    allowed = {
        "database": {"host", "port", "name", "user", "sslmode", "connect_timeout_seconds",
                     "statement_timeout_ms", "lock_timeout_ms"},
        "source": {"profile", "schema", "alarm_table", "event_table", "timezone"},
        "limits": {"preview_rows", "max_field_bytes", "max_output_bytes"},
        "collection": {"source_id", "generation_id", "collection_enabled", "marker_verified", "scan_mode",
                       "history_start", "history_end", "all_history", "page_rows", "max_pages", "overlap_seconds",
                       "reconcile_ids", "queue_bytes", "min_free_bytes", "privacy"},
        "upload": {"upload_url", "upload_enabled", "upload_ca_file"},
        "schedule": {"interval_seconds", "schedule_mode", "schedule_timezone", "schedule_time", "schedule_weekday"},
    }
    if set(data) - {"version", *allowed} or type(data.get("version")) is not int or data["version"] != 1:
        raise CollectorError("Expected configuration version 1 with approved settings sections only.")
    for name, keys in allowed.items():
        section = data.get(name, {})
        if not isinstance(section, dict) or set(section) - keys:
            raise CollectorError(f"Unknown or invalid setting in {name}; passwords must not be stored in TOML.")
    db, source, limits = (data.get(name, {}) for name in ("database", "source", "limits"))
    extra = {}
    defaults = {f.name: f.default for f in fields(CollectorConfig)}
    for section in ("collection", "upload", "schedule"):
        for name in allowed[section]:
            value = data.get(section, {}).get(name, defaults[name])
            if type(value) is not type(defaults[name]):
                raise CollectorError(f"Invalid setting type for {name}.")
            extra[name] = value
    for name, low, high in (("page_rows", 1, 100), ("max_pages", 1, 100), ("overlap_seconds", 1, 86400),
                            ("reconcile_ids", 1, 10000000), ("queue_bytes", 1048576, 10737418240),
                            ("min_free_bytes", 0, 10737418240), ("interval_seconds", 10, 604800),
                            ("schedule_weekday", 0, 6)):
        if not low <= extra[name] <= high:
            raise CollectorError(f"{name} must be from {low} to {high}.")
    for name in ("source_id", "generation_id"):
        if extra[name]:
            try:
                if str(UUID(extra[name])) != extra[name]:
                    raise ValueError()
            except ValueError:
                raise CollectorError(f"{name} must be a canonical UUID.") from None
    from datetime import datetime, time
    for name in ("history_start", "history_end"):
        if extra[name]:
            try:
                if datetime.fromisoformat(extra[name]).tzinfo is not None:
                    raise ValueError()
            except ValueError:
                raise CollectorError("History bounds must be source-local ISO timestamps without an offset.") from None
    if extra['history_start'] and extra['history_end'] and datetime.fromisoformat(extra['history_start']) >= datetime.fromisoformat(extra['history_end']):
        raise CollectorError("History end must be later than history start.")
    if extra['scan_mode'] not in {'marker', 'id_range'} or extra['privacy'] not in {'upload_all', 'omit', 'hash'}:
        raise CollectorError("Invalid scan mode or operator privacy policy.")
    if extra['scan_mode'] == 'marker' and not extra['marker_verified']:
        raise CollectorError("Marker mode requires locally verified change-marker semantics; use id_range otherwise.")
    if extra['schedule_mode'] not in {'interval', 'daily', 'weekly'}:
        raise CollectorError("Invalid local schedule mode.")
    try:
        ZoneInfo(extra['schedule_timezone'])
        if not re.fullmatch(r'\d{2}:\d{2}', extra['schedule_time']):
            raise ValueError()
        time.fromisoformat(extra['schedule_time'])
    except (ValueError, ZoneInfoNotFoundError):
        raise CollectorError("Invalid schedule timezone or HH:MM time.") from None
    if extra['upload_url']:
        try:
            url = urlsplit(extra['upload_url'])
            if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError()
            if url.port is not None and url.port < 1:
                raise ValueError()
        except ValueError:
            raise CollectorError("Upload destination must be a fixed HTTPS URL without credentials or query parameters.") from None
    if extra['upload_enabled'] and not extra['upload_url']:
        raise CollectorError("Set an HTTPS destination before enabling uploads.")
    host = _text(db, "host", "localhost")
    if not re.fullmatch(r"[A-Za-z0-9_.:\-]+", host):
        raise CollectorError("host must be a single hostname or IP address, not a connection string.")
    sslmode = db.get("sslmode", "verify-full")
    if not isinstance(sslmode, str) or sslmode not in {"disable", "require", "verify-ca", "verify-full"}:
        raise CollectorError("sslmode must be disable, require, verify-ca, or verify-full.")
    if sslmode == "disable" and host not in {"localhost", "127.0.0.1", "::1"}:
        raise CollectorError("Unencrypted database connections are permitted only on loopback.")
    if source.get("profile", PROFILE) != PROFILE:
        raise CollectorError("Unsupported source profile.")
    timezone = source.get("timezone", "")
    if not isinstance(timezone, str) or len(timezone) > 128:
        raise CollectorError("timezone must be an IANA timezone name or empty.")
    if timezone:
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise CollectorError("Unknown source timezone; install tzdata and check the IANA name.") from None
    schema = identifier(source.get("schema", "public"))
    alarm = identifier(source.get("alarm_table", "alarmhistory"))
    event = identifier(source.get("event_table", "eventhistory"))
    if alarm.casefold() == event.casefold():
        raise CollectorError("Alarm and event table mappings must be different.")
    return CollectorConfig(
        path=path, host=host, port=_integer(db, "port", 5432, 1, 65535),
        database=_text(db, "name"), user=_text(db, "user"), sslmode=sslmode,
        connect_timeout_seconds=_integer(db, "connect_timeout_seconds", 5, 1, 60),
        statement_timeout_ms=_integer(db, "statement_timeout_ms", 5000, 100, 60000),
        lock_timeout_ms=_integer(db, "lock_timeout_ms", 1000, 100, 5000),
        schema=schema, alarm_table=alarm, event_table=event, timezone=timezone,
        preview_rows=_integer(limits, "preview_rows", 20, 1, 100),
        max_field_bytes=_integer(limits, "max_field_bytes", 4096, 128, 16384),
        max_output_bytes=_integer(limits, "max_output_bytes", 262144, 1024, 1048576),
        **extra,
    )
