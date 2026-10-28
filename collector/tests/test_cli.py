from contextlib import redirect_stderr, redirect_stdout
import io
import json
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from collector.cli import main
from collector.config import EXAMPLE
from collector.errors import CollectorError


class CliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "config.toml"
        self.path.write_text(EXAMPLE, encoding="utf-8")
        self.stdout, self.stderr = io.StringIO(), io.StringIO()

    def run_cli(self, *args):
        with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
            return main(["--config", str(self.path), *args])

    def test_config_check_never_reads_secret_or_connects(self):
        with patch("collector.cli.SourceReader") as reader, patch("collector.cli.secrets.load_password") as password:
            self.assertEqual(self.run_cli("check-config"), 0)
            reader.assert_not_called()
            password.assert_not_called()
        self.assertFalse(json.loads(self.stdout.getvalue())["cloud_uploads_enabled"])

    def test_errors_do_not_dump_connection_exceptions_or_tracebacks(self):
        with patch("collector.cli.secrets.load_password", side_effect=CollectorError("Cannot unlock database password.")):
            self.assertEqual(self.run_cli("test-connection"), 1)
        self.assertEqual(self.stdout.getvalue(), "")
        self.assertNotIn("Traceback", self.stderr.getvalue())

    def test_preview_is_explicitly_not_an_upload_or_checkpoint(self):
        with patch("collector.cli.secrets.load_password", return_value="TEST-ONLY-password"), \
                patch("collector.cli.SourceReader") as reader:
            reader.return_value.preview.return_value = []
            self.assertEqual(self.run_cli("preview", "--table", "alarmhistory"), 0)
        result = json.loads(self.stdout.getvalue())
        self.assertEqual(result["mode"], "preview_only")
        self.assertFalse(result["checkpoint_changed"])
        self.assertNotIn("TEST-ONLY-password", self.stdout.getvalue())

    def test_password_confirmation_failure_preserves_existing_secret(self):
        with patch("collector.cli.getpass", side_effect=["first", "second"]), \
                patch("collector.cli.secrets.save_password") as save:
            self.assertEqual(self.run_cli("set-password"), 1)
            save.assert_not_called()
        self.assertNotIn("first", self.stderr.getvalue())

    def test_gui_dispatch_does_not_open_a_database_or_read_a_secret(self):
        from unittest.mock import Mock
        gui = Mock()
        gui.launch.return_value = 0
        with patch.dict(sys.modules, {"collector.gui": gui}), \
                patch("collector.cli.SourceReader") as reader, \
                patch("collector.cli.secrets.load_password") as password:
            self.assertEqual(self.run_cli("gui"), 0)
            gui.launch.assert_called_once_with(self.path)
            reader.assert_not_called()
            password.assert_not_called()

    def test_missing_tk_has_an_actionable_error_instead_of_a_traceback(self):
        with patch.dict(sys.modules, {"collector.gui": None}):
            self.assertEqual(self.run_cli("gui"), 1)
        self.assertIn("Tcl/Tk", self.stderr.getvalue())
        self.assertNotIn("Traceback", self.stderr.getvalue())
