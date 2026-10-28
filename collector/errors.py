"""Errors safe to display without database exception text or credentials."""


class CollectorError(Exception):
    """An actionable, redacted collector fault."""
