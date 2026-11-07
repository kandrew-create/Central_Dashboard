"""Host timezone metadata for display; never an implicit source timestamp zone."""
import os
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def windows_timezone():
    name = os.environ.get('COLLECTOR_WINDOWS_TIMEZONE', '')
    try:
        return name if name and ZoneInfo(name) else ''
    except (ValueError, ZoneInfoNotFoundError):
        return ''


def next_run_text(stamp, schedule_timezone):
    name = windows_timezone() or schedule_timezone
    if not stamp:
        return 'Not scheduled', name
    return datetime.fromtimestamp(stamp, ZoneInfo(name)).strftime('%Y-%m-%d %H:%M:%S %Z'), name
