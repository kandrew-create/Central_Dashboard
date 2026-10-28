"""Explicit source contract. No discovery or reads of Heartbeat/unknown tables."""
from collector.records import PERSONAL_FIELDS, TIME_FIELDS

ALARM_COLUMNS = {
    "id": "integer",
    **{name: "timestamp without time zone" for name in TIME_FIELDS["alarmhistory"]},
    **{name + "_ms": "integer" for name in TIME_FIELDS["alarmhistory"]},
    **{name: "boolean" for name in ("al_ack", "al_active", "al_ack_req", "al_deleted")},
    **{name: "text" for name in ("al_tag", "al_message", "al_selection", "al_station", "al_custom1",
                               *PERSONAL_FIELDS["alarmhistory"])},
    "al_tag_value": "character varying", "al_prev_tag_value": "character varying",
    "al_group": "integer", "al_priority": "integer", "al_type": "integer",
}
EVENT_COLUMNS = {
    "id": "integer", "ev_type": "integer",
    **{name: "timestamp without time zone" for name in TIME_FIELDS["eventhistory"]},
    **{name + "_ms": "integer" for name in TIME_FIELDS["eventhistory"]},
    **{name: "text" for name in ("ev_info", "ev_source", "ev_message", "ev_station",
                               *PERSONAL_FIELDS["eventhistory"])},
    "ev_deleted": "boolean", "ev_value": "character varying", "ev_prev_value": "character varying",
}
COLUMNS = {"alarmhistory": ALARM_COLUMNS, "eventhistory": EVENT_COLUMNS}
