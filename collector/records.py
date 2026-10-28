"""Preserve source values and flag timestamp uncertainty without guessing."""
from datetime import datetime, timezone
import hashlib
import json
from zoneinfo import ZoneInfo


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def source_time(local, milliseconds, timezone_name):
    result = {"local": local.isoformat(timespec="microseconds") if isinstance(local, datetime) else local,
              "milliseconds": milliseconds, "utc": None, "quality": "missing"}
    if local is None:
        return result
    if (not isinstance(local, datetime) or local.tzinfo is not None or local.microsecond != 0
            or type(milliseconds) is not int or not 0 <= milliseconds <= 999):
        result["quality"] = "invalid"
        return result
    if not timezone_name:
        result["quality"] = "timezone_unknown"
        return result
    combined = local.replace(microsecond=milliseconds * 1000)
    zone = ZoneInfo(timezone_name)
    candidates = set()
    try:
        for fold in (0, 1):
            utc = combined.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
            if utc.astimezone(zone).replace(tzinfo=None) == combined:
                candidates.add(utc)
    except (ValueError, OverflowError):
        result["quality"] = "invalid"
        return result
    if not candidates:
        result["quality"] = "nonexistent"
    elif len(candidates) > 1:
        result["quality"] = "ambiguous"
    else:
        result["quality"] = "known"
        result["utc"] = candidates.pop().isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return result


TIME_FIELDS = {
    "alarmhistory": ("al_start_time", "al_norm_time", "al_ack_time", "al_event_time", "last_update"),
    "eventhistory": ("ev_time", "last_update"),
}
PERSONAL_FIELDS = {
    "alarmhistory": ("al_user", "al_user_full", "al_user_comment"),
    "eventhistory": ("ev_user", "ev_user_full", "ev_comment"),
}


def preview_record(table, row, timezone_name, include_user_fields=False):
    original = {key: value.isoformat(timespec="microseconds") if isinstance(value, datetime) else value
                for key, value in row.items()}
    # Change markers are represented separately: marker-only changes do not change content identity.
    content = {key: value for key, value in original.items() if key not in {"last_update", "last_update_ms"}}
    content_hash = hashlib.sha256(canonical_bytes(content)).hexdigest()
    if not include_user_fields:
        original = {key: value for key, value in original.items() if key not in PERSONAL_FIELDS[table]}
    return {
        "source_table": table, "record_type": "alarm" if table == "alarmhistory" else "event",
        "source_record_id": row["id"], "content_hash": content_hash, "original": original,
        "source_timezone": timezone_name or None,
        "times": {name: source_time(row[name], row[name + "_ms"], timezone_name) for name in TIME_FIELDS[table]},
        # A preview cannot establish precedence between observations, even with a valid timestamp.
        "ordering_uncertain": True,
        "personal_fields": "included" if include_user_fields else "omitted_from_preview",
    }
