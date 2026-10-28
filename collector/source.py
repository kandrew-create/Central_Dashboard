"""Read-only, short-lived, bounded source access for local commissioning."""
from contextlib import contextmanager

from collector.config import TABLES
from collector.errors import CollectorError
from collector.profiles.ecostruxure import COLUMNS
from collector.records import canonical_bytes, preview_record


def _driver():
    try:
        import psycopg
        from psycopg.rows import dict_row
        from psycopg import sql
    except ImportError:
        raise CollectorError("Install the declared collector dependencies before connecting.") from None
    return psycopg, dict_row, sql


def connection_error_message(error):
    """Classify libpq faults internally; never display its credential-bearing text."""
    state = getattr(error, "sqlstate", None)
    message = str(error).casefold()
    if "does not support ssl" in message:
        return ("PostgreSQL at this address does not support TLS. For a database on this PC, "
                "set Database TLS to disable and save settings. For a remote database, have its administrator enable TLS.")
    if "certificate" in message or "ssl handshake" in message or "tls handshake" in message:
        return "Database TLS verification failed. Check the PostgreSQL certificate, trusted CA, and hostname."
    if "no pg_hba.conf entry" in message:
        return "PostgreSQL does not allow this connection. Ask its administrator to check the host authentication rule."
    if state == "3D000" or ("database" in message and "does not exist" in message):
        return "The selected PostgreSQL database does not exist. Check the database name, host, and port."
    if "role" in message and "does not exist" in message:
        return "The selected PostgreSQL username does not exist. Check its exact spelling and capitalization."
    if state in {"28P01", "28000"} or "password authentication failed" in message or "no password supplied" in message:
        return ("PostgreSQL rejected the username or password. Check the exact username, including capitalization, "
                "then enter the PostgreSQL login password, store it, and test again.")
    if state == "42501":
        return "The source account lacks required read access. Ask its administrator to grant access to the two approved tables."
    if state == "42P01":
        return "An approved source table was not found. Check the configured schema and approved table names."
    if state == "42703":
        return "An approved source column was not found. Check that the source matches the approved EcoStruxure profile."
    if "could not translate host name" in message or "getaddrinfo failed" in message:
        return "The PostgreSQL hostname could not be resolved. Check the Host setting."
    if "connection refused" in message or "actively refused" in message:
        return "PostgreSQL is not accepting connections at this address. Check that its service is running and the host/port are correct."
    if "timeout expired" in message or "timed out" in message:
        return "The PostgreSQL connection timed out. Check the host, port, network access, and connection timeout."
    return "Source access failed; check connection, permissions, schema, and timestamp values."


class SourceReader:
    def __init__(self, config, password):
        self.config = config
        self._password = password

    @contextmanager
    def session(self):
        psycopg, dict_row, _sql = _driver()
        config = self.config
        try:
            with psycopg.connect(
                host=config.host, port=config.port, dbname=config.database, user=config.user,
                password=self._password, sslmode=config.sslmode,
                connect_timeout=config.connect_timeout_seconds, application_name="linker_scada_collector",
                options=(f"-c default_transaction_read_only=on -c statement_timeout={config.statement_timeout_ms} "
                         f"-c lock_timeout={config.lock_timeout_ms} -c idle_in_transaction_session_timeout=10000"),
                autocommit=True, row_factory=dict_row,
            ) as connection:
                self._validate_account(connection)
                yield connection
        except psycopg.errors.QueryCanceled:
            raise CollectorError("Source query timed out; review the local query limits and source workload.") from None
        except psycopg.errors.LockNotAvailable:
            raise CollectorError("Source table is busy; the bounded lock wait expired.") from None
        except psycopg.Error as error:
            raise CollectorError(connection_error_message(error)) from None
        except (UnicodeError, ValueError, OverflowError):
            raise CollectorError("Source access failed; check connection, permissions, schema, and timestamp values.") from None

    def _validate_account(self, connection):
        role = connection.execute("""SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls
            FROM pg_catalog.pg_roles WHERE rolname = current_user""").fetchone()
        if role is None or any(role.values()):
            raise CollectorError("Use a dedicated, unprivileged read-only PostgreSQL account.")
        if connection.execute("SHOW default_transaction_read_only").fetchone()["default_transaction_read_only"] != "on":
            raise CollectorError("Read-only source sessions are required.")

    def _validate_table(self, connection, table):
        physical = self.config.table(table)
        metadata = connection.execute("""SELECT column_name, data_type, is_nullable, identity_generation
            FROM information_schema.columns WHERE table_schema = %s AND table_name = %s""",
            (self.config.schema, physical)).fetchall()
        actual = {column["column_name"]: column for column in metadata}
        expected_identity = "ALWAYS" if table == "alarmhistory" else "BY DEFAULT"
        if (any(name not in actual or actual[name]["data_type"] != kind for name, kind in COLUMNS[table].items())
                or actual.get("id", {}).get("is_nullable") != "NO"
                or actual.get("id", {}).get("identity_generation") != expected_identity):
            raise CollectorError(f"{table} does not match the approved EcoStruxure v1 schema.")
        permissions = connection.execute("""SELECT c.relkind,
            pg_has_role(c.relowner, 'MEMBER') AS owns_table,
            has_table_privilege(c.oid, 'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') AS can_write,
            has_any_column_privilege(c.oid, 'INSERT,UPDATE,REFERENCES') AS can_write_column,
            has_schema_privilege(c.relnamespace, 'CREATE') AS can_create
            FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %s AND c.relname = %s""", (self.config.schema, physical)).fetchone()
        if (not permissions or permissions["relkind"] != "r"
                or any(permissions[key] for key in ("owns_table", "can_write", "can_write_column", "can_create"))):
            raise CollectorError("Source account must not own/write approved tables or create schema objects.")

    def check(self):
        _psycopg, _dict_row, sql = _driver()
        with self.session() as connection:
            for table in TABLES:
                self._validate_table(connection, table)
                columns = sql.SQL(", ").join(sql.Identifier(name) for name in COLUMNS[table])
                connection.execute(sql.SQL("SELECT {} FROM {} LIMIT 0").format(columns,
                    sql.Identifier(self.config.schema, self.config.table(table))))
        return {"status": "connected", "read_only": True, "profile": "ecostruxure_machine_scada_expert_v1",
                "approved_tables": list(TABLES), "source_timezone": self.config.timezone or None}

    def bounds(self):
        """Only approved-table metadata and bounded head queries; never table counts."""
        _pg, _rows, sql = _driver()
        result = {}
        with self.session() as connection:
            with connection.transaction():
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                database = connection.execute("SELECT oid FROM pg_catalog.pg_database WHERE datname=current_database()").fetchone()['oid']
                for table in TABLES:
                    self._validate_table(connection, table)
                    relation = sql.Identifier(self.config.schema, self.config.table(table))
                    meta = connection.execute("""SELECT c.oid, c.relfilenode FROM pg_catalog.pg_class c
                        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
                        WHERE n.nspname=%s AND c.relname=%s""", (self.config.schema, self.config.table(table))).fetchone()
                    head = connection.execute(sql.SQL("SELECT id FROM {} ORDER BY id DESC LIMIT 1").format(relation)).fetchone()
                    stamp = connection.execute(sql.SQL("""SELECT last_update, last_update_ms, id FROM {}
                        WHERE last_update IS NOT NULL AND last_update_ms BETWEEN 0 AND 999
                        AND date_trunc('second',last_update)=last_update
                        ORDER BY last_update DESC,last_update_ms DESC,id DESC LIMIT 1""").format(relation)).fetchone() if self.config.scan_mode == 'marker' else None
                    result[table] = {'fingerprint': [database, meta['oid'], meta['relfilenode']],
                                     'high_id': head['id'] if head else None,
                                     'marker': [stamp['last_update'].isoformat(timespec='microseconds'), stamp['last_update_ms'], stamp['id']] if stamp else None}
        return result

    def scan_page(self, table, phase, bound, cursor=None, lower=None, history=None):
        """A single bounded page under a persisted cycle bound; NULL markers use ID scans."""
        from datetime import datetime
        _pg, _rows, sql = _driver()
        self.config.table(table)
        terms, params = [], {'limit': self.config.page_rows, 'field_bytes': self.config.max_field_bytes}
        if bound['high_id'] is None:
            return []
        terms.append(sql.SQL('id <= %(high)s'))
        params['high'] = bound['high_id']
        if phase == 'marker':
            if not bound['marker']:
                return []
            terms.append(sql.SQL("last_update IS NOT NULL AND last_update_ms BETWEEN 0 AND 999 AND date_trunc('second',last_update)=last_update"))
            terms.append(sql.SQL('(last_update,last_update_ms,id) <= (%(stamp)s,%(ms)s,%(marker_id)s)'))
            params.update(stamp=datetime.fromisoformat(bound['marker'][0]), ms=bound['marker'][1], marker_id=bound['marker'][2])
            if lower:
                terms.append(sql.SQL('last_update >= %(lower)s'))
                params['lower'] = datetime.fromisoformat(lower)
            if cursor:
                terms.append(sql.SQL('(last_update,last_update_ms,id) > (%(cs)s,%(cm)s,%(ci)s)'))
                params.update(cs=datetime.fromisoformat(cursor[0]), cm=cursor[1], ci=cursor[2])
            order = sql.SQL('last_update,last_update_ms,id')
        else:
            if cursor is not None:
                terms.append(sql.SQL('id > %(cursor)s'))
                params['cursor'] = cursor
            if lower is not None:
                terms.append(sql.SQL('id >= %(lower_id)s'))
                params['lower_id'] = lower
            order = sql.SQL('id')
        if history:
            stamp = (sql.SQL('coalesce(al_start_time,al_event_time,last_update)') if table == 'alarmhistory'
                     else sql.SQL('coalesce(ev_time,last_update)'))
            # Undated evidence cannot be safely excluded by a date range.
            terms.append(sql.SQL('(id > %(initial_high)s OR {} IS NULL OR ({} >= %(hs)s AND {} < %(he)s))').format(stamp, stamp, stamp))
            params.update(hs=datetime.fromisoformat(history['start']), he=datetime.fromisoformat(history['end']),
                          initial_high=history['initial_high'] if history['initial_high'] is not None else -2147483649)
        selected, oversized = [], []
        for name, kind in COLUMNS[table].items():
            column = sql.Identifier(name)
            if kind in {'text', 'character varying'}:
                check = sql.SQL('coalesce(octet_length({}) > %(field_bytes)s,false)').format(column)
                oversized.append(check)
                selected.append(sql.SQL('CASE WHEN {} THEN NULL ELSE {} END AS {}').format(check, column, column))
            else:
                selected.append(column)
        selected.append(sql.SQL('({}) AS _collector_oversized').format(sql.SQL(' OR ').join(oversized)))
        query = sql.SQL('SELECT {} FROM {} WHERE {} ORDER BY {} LIMIT %(limit)s').format(
            sql.SQL(',').join(selected), sql.Identifier(self.config.schema, self.config.table(table)), sql.SQL(' AND ').join(terms), order)
        with self.session() as connection:
            self._validate_table(connection, table)
            rows = connection.execute(query, params).fetchall()
        if any(row.pop('_collector_oversized') for row in rows):
            raise CollectorError('A source field exceeds max_field_bytes; collection progress was preserved.')
        if sum(len(canonical_bytes(preview_record(table, row, self.config.timezone, True))) for row in rows) > self.config.max_output_bytes:
            raise CollectorError('Collection page exceeds max_output_bytes; reduce page_rows.')
        return rows

    def preview(self, table, after_id=None, limit=None, include_user_fields=False):
        self.config.table(table)
        limit = self.config.preview_rows if limit is None else limit
        if type(limit) is not int or not 1 <= limit <= self.config.preview_rows:
            raise CollectorError(f"Preview limit must be from 1 to {self.config.preview_rows}.")
        if after_id is not None and (type(after_id) is not int or not -2147483648 <= after_id <= 2147483647):
            raise CollectorError("after-id must be a PostgreSQL integer.")
        _psycopg, _dict_row, sql = _driver()
        selected, checks = [], []
        for name, kind in COLUMNS[table].items():
            column = sql.Identifier(name)
            if kind in {"text", "character varying"}:
                oversized = sql.SQL("coalesce(octet_length({}) > %(field_bytes)s, false)").format(column)
                checks.append(oversized)
                selected.append(sql.SQL("CASE WHEN {} THEN NULL ELSE {} END AS {}").format(
                    oversized, column, column))
            else:
                selected.append(column)
        selected.append(sql.SQL("({}) AS _collector_oversized").format(sql.SQL(" OR ").join(checks)))
        where = sql.SQL("") if after_id is None else sql.SQL("WHERE id > %(after)s")
        query = sql.SQL("SELECT {} FROM {} {} ORDER BY id LIMIT %(limit)s").format(
            sql.SQL(", ").join(selected), sql.Identifier(self.config.schema, self.config.table(table)), where)
        with self.session() as connection:
            self._validate_table(connection, table)
            rows = connection.execute(query, {"field_bytes": self.config.max_field_bytes,
                                             "after": after_id, "limit": limit}).fetchall()
        records = []
        output_bytes = 0
        for row in rows:
            if row.pop("_collector_oversized"):
                raise CollectorError("A source text field exceeds max_field_bytes; no truncated preview is returned.")
            record = preview_record(table, row, self.config.timezone, include_user_fields)
            output_bytes += len(canonical_bytes(record))
            if output_bytes > self.config.max_output_bytes:
                raise CollectorError("Preview exceeds max_output_bytes; request fewer records.")
            records.append(record)
        return records
