"""Dependency-free checks of release boundaries and migration packaging."""
import ast
from pathlib import Path
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RepositoryTests(unittest.TestCase):
    def test_collector_has_no_listener_or_process_execution_path(self):
        # This guards the scaffold only. Runtime network evidence is still required
        # when service/uploader code is added; do not report this as that evidence.
        forbidden_modules = {"socketserver", "http.server", "flask", "fastapi", "uvicorn", "subprocess"}
        forbidden_calls = {"bind", "listen", "start_server", "create_server", "exec", "eval"}
        for path in (ROOT / "collector").rglob("*.py"):
            if "tests" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertFalse({alias.name for alias in node.names} & forbidden_modules, str(path))
                if isinstance(node, ast.ImportFrom):
                    self.assertNotIn(node.module, forbidden_modules, str(path))
                if isinstance(node, ast.Call):
                    name = getattr(node.func, "attr", getattr(node.func, "id", ""))
                    # Tk event binding is not a network socket bind. Keep the
                    # socket guard while allowing explicit desktop event names.
                    if name == 'bind' and path.name == 'gui.py' and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == '<Configure>':
                        continue
                    self.assertNotIn(name, forbidden_calls, str(path))

    def test_every_python_file_parses(self):
        for folder in ("server", "collector", "tests"):
            for path in (ROOT / folder).rglob("*.py"):
                with self.subTest(path=str(path.relative_to(ROOT))):
                    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_migration_sql_included_in_package(self):
        config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn("sql/*.sql", config["tool"]["setuptools"]["package-data"]["server.migrations"])


if __name__ == "__main__":
    unittest.main()
