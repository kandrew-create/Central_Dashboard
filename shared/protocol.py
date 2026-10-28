"""Strict v1 protocol. Hashes describe transmitted evidence, not receipt order."""
from datetime import datetime
import hashlib
import json
import re
from uuid import UUID

from collector.config import TABLES
from collector.profiles.ecostruxure import COLUMNS
from collector.records import PERSONAL_FIELDS, canonical_bytes, preview_record

MAX_BATCH_BYTES = 1048576
MAX_RECORDS = 100


class ProtocolError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def uuid_text(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ProtocolError("Expected a canonical UUID.")
    return value


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ProtocolError("Duplicate JSON key.")
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ProtocolError("Nonfinite JSON.")))
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ProtocolError("Invalid JSON.") from error


def marker(original):
    value, ms = original.get("last_update"), original.get("last_update_ms")
    if value is None or type(ms) is not int or not 0 <= ms <= 999:
        return None
    try:
        stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
        if stamp.tzinfo is not None or stamp.microsecond:
            return None
        return stamp.isoformat(timespec="microseconds"), ms
    except (ValueError, TypeError, AttributeError):
        return None


def record_content_hash(original):
    return digest({k: v for k, v in original.items() if k not in {"last_update", "last_update_ms"}})


def revision_key(record):
    return digest([record["original"].get("last_update"), record["original"].get("last_update_ms"),
                   record_content_hash(record["original"])])


def validate_record(record, privacy):
    if not isinstance(record, dict) or set(record) != {"table", "original", "timezone", "ordering_uncertain"}:
        raise ProtocolError("Invalid record envelope.")
    table, original = record["table"], record["original"]
    if not isinstance(table, str) or table not in TABLES or not isinstance(original, dict):
        raise ProtocolError("Unapproved source table.")
    expected = set(COLUMNS[table])
    if privacy == "omit":
        expected -= set(PERSONAL_FIELDS[table])
    if set(original) != expected or type(record["ordering_uncertain"]) is not bool:
        raise ProtocolError("Invalid source field set.")
    zone = record["timezone"]
    if not isinstance(zone, str) or len(zone) > 128:
        raise ProtocolError("Invalid source timezone.")
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    if zone:
        try:
            ZoneInfo(zone)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise ProtocolError("Unknown timezone.") from error
    row = {}
    for name, value in original.items():
        kind = COLUMNS[table][name]
        if value is None and name != "id":
            row[name] = None
            continue
        if kind == "integer":
            valid = type(value) is int and -2147483648 <= value <= 2147483647
        elif kind == "boolean":
            valid = type(value) is bool
        elif kind == "timestamp without time zone":
            try:
                parsed = datetime.fromisoformat(value) if isinstance(value, str) else None
                valid = parsed is not None and parsed.tzinfo is None and parsed.isoformat(timespec="microseconds") == value
            except ValueError:
                valid = False
            if valid:
                row[name] = parsed
                continue
        else:
            valid = isinstance(value, str) and "\x00" not in value and len(value.encode("utf-8")) <= 4096
            if valid and privacy == 'hash' and name in PERSONAL_FIELDS[table]:
                valid = re.fullmatch(r'hmac-sha256:[0-9a-f]{64}',value) is not None
        if not valid:
            raise ProtocolError("Invalid source field value.")
        row[name] = value
    for name in PERSONAL_FIELDS[table]:
        row.setdefault(name, None)
    result = preview_record(table, row, zone, include_user_fields=True)
    result["original"] = original
    result["content_hash"] = record_content_hash(original)
    result["ordering_uncertain"] = (record["ordering_uncertain"] or marker(original) is None
                                     or result["times"]["last_update"]["quality"] != "known")
    result["revision_key"] = revision_key(record)
    return result


def make_batch(source_id, generation_id, batch_id, records, privacy="upload_all", is_backfill=False):
    batch = dict(schema_version=1, source_id=source_id, generation_id=generation_id, batch_id=batch_id,
                 privacy=privacy, is_backfill=is_backfill, records=records)
    batch["payload_hash"] = digest(batch)
    return batch


def validate_batch(batch):
    keys = {"schema_version", "source_id", "generation_id", "batch_id", "privacy", "is_backfill", "records", "payload_hash"}
    if not isinstance(batch, dict) or set(batch) != keys or type(batch["schema_version"]) is not int or batch["schema_version"] != 1:
        raise ProtocolError("Unsupported batch envelope.")
    for name in ("source_id", "generation_id", "batch_id"):
        try:
            uuid_text(batch[name])
        except (ValueError, TypeError, AttributeError) as error:
            raise ProtocolError("Invalid batch identity.") from error
    if batch["privacy"] not in ("upload_all", "omit", "hash") or type(batch["is_backfill"]) is not bool:
        raise ProtocolError("Invalid batch policy.")
    if not isinstance(batch["records"], list) or not 1 <= len(batch["records"]) <= MAX_RECORDS:
        raise ProtocolError("Invalid record count.")
    if len(canonical_bytes(batch)) > MAX_BATCH_BYTES or batch["payload_hash"] != digest({k: v for k, v in batch.items() if k != "payload_hash"}):
        raise ProtocolError("Invalid batch hash or size.")
    return [validate_record(record, batch["privacy"]) for record in batch["records"]]
