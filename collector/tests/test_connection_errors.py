import unittest
from unittest.mock import patch

import psycopg

from collector.desktop import default_config
from collector.errors import CollectorError
from collector.source import SourceReader, connection_error_message


class ConnectionErrorTests(unittest.TestCase):
    def test_supported_connection_failures_have_actionable_redacted_messages(self):
        cases = (
            ("server does not support SSL, but SSL was required", "does not support TLS"),
            ('password authentication failed for user "private-user"', "rejected the username or password"),
            ('database "private-db" does not exist', "database does not exist"),
            ('role "private-user" does not exist', "username does not exist"),
            ('no pg_hba.conf entry for host "private-host"', "host authentication rule"),
            ("SSL error: certificate verify failed", "TLS verification failed"),
            ("connection failed: Connection refused", "not accepting connections"),
            ("connection timeout expired", "connection timed out"),
            ('could not translate host name "private-host"', "hostname could not be resolved"),
        )
        for message, expected in cases:
            with self.subTest(message=message):
                fault = psycopg.OperationalError(message + " password=TEST-ONLY-do-not-display")
                result = connection_error_message(fault)
                self.assertIn(expected, result)
                self.assertNotIn("TEST-ONLY", result)
                self.assertNotIn("private-", result)

    def test_sqlstate_failures_are_redacted_without_echoing_database_details(self):
        for error, expected in (
            (psycopg.errors.InvalidPassword("private-login"), "rejected the username or password"),
            (psycopg.errors.InsufficientPrivilege("private-table"), "required read access"),
            (psycopg.errors.UndefinedTable("private-table"), "source table was not found"),
            (psycopg.errors.UndefinedColumn("private-column"), "source column was not found"),
            (psycopg.errors.InvalidCatalogName("private-db"), "database does not exist"),
        ):
            with self.subTest(expected=expected):
                result = connection_error_message(error)
                self.assertIn(expected, result)
                self.assertNotIn("private-", result)

    def test_unknown_errors_never_echo_libpq_text(self):
        result = connection_error_message(psycopg.OperationalError("secret=TEST-ONLY-password"))
        self.assertNotIn("TEST-ONLY", result)
        self.assertIn("Source access failed", result)

    def test_reader_uses_the_safe_message_when_connection_fails(self):
        config = default_config("collector-local/config.toml")
        reader = SourceReader(config, "TEST-ONLY-password")
        with patch("psycopg.connect", side_effect=psycopg.OperationalError(
                "server does not support SSL, but SSL was required")):
            with self.assertRaisesRegex(CollectorError, "does not support TLS"):
                reader.check()
