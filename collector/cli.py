"""Local setup, preview, collection, scheduling and delivery commands; no listener."""
import argparse
from getpass import getpass
import json
from pathlib import Path
import sys

from collector import __version__
from collector.config import EXAMPLE, PROFILE, TABLES, load_config
from collector.errors import CollectorError
from collector import secrets
from collector.source import SourceReader


def parser():
    cli = argparse.ArgumentParser(description="SCADA collector local commissioning tool")
    cli.add_argument("--version", action="version", version=__version__)
    cli.add_argument("--config", type=Path, default=Path("collector-local/config.toml"))
    commands = cli.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Create private local configuration in a new directory (Windows)")
    commands.add_parser("set-password", help="Protect the prompted database password with current-user DPAPI")
    commands.add_parser("check-config", help="Validate local configuration without a database connection")
    commands.add_parser("test-connection", help="Check read-only account and both approved table schemas")
    commands.add_parser("gui", help="Open the local desktop setup and preview window")
    commands.add_parser('collect', help='Run one bounded collection/delivery cycle')
    commands.add_parser('run', help='Run the durable local scheduler until stopped')
    commands.add_parser('status', help='Show local queue, schedule and delivery status')
    commands.add_parser('set-upload-token', help='Protect the prompted upload credential with DPAPI')
    commands.add_parser('set-privacy-key', help='Protect the prompted operator-field hashing key')
    generation = commands.add_parser('new-generation', help='Authorize a provisioned generation in a new setup; retains old pending state')
    generation.add_argument('--generation-id', required=True)
    generation.add_argument('--authorization', required=True)
    reexport = commands.add_parser('re-export',help='Authorize re-reading the existing approved history scope after central recovery')
    reexport.add_argument('--authorization',required=True)
    preview = commands.add_parser("preview", help="Read a bounded sample; does not upload or advance a checkpoint")
    preview.add_argument("--table", choices=TABLES, required=True)
    preview.add_argument("--after-id", type=int, help="Local preview pagination only, not an extraction checkpoint")
    preview.add_argument("--limit", type=int)
    preview.add_argument("--include-user-fields", action="store_true", help="Include operator fields in this local preview")
    return cli


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "gui":
            try:
                from collector.gui import launch
            except ImportError:
                raise CollectorError("The desktop interface requires Python's Tcl/Tk component. Enable Tcl/Tk in your Python installation.") from None
            return launch(args.config)
        if args.command == "init":
            secrets.initialize(args.config, EXAMPLE)
            result = {"status": "created", "next": "Edit local configuration, then run set-password under the collector account."}
        else:
            config = load_config(args.config)
            if args.command == "set-password":
                password = getpass("Database password (not displayed): ")
                if password != getpass("Confirm database password: "):
                    raise CollectorError("Passwords do not match; existing credentials were preserved.")
                secrets.save_password(config.password_path, password)
                result = {"status": "password_protected", "scope": "current Windows account"}
            elif args.command in {'set-upload-token', 'set-privacy-key'}:
                value = getpass('Credential/key (not displayed): ')
                if len(value) < 32 or value != getpass('Confirm credential/key: '):
                    raise CollectorError('Enter a matching credential/key of at least 32 characters.')
                if args.command=='set-upload-token' and (not value.isascii() or not 43 <= len(value) <= 256):
                    raise CollectorError('Enter the server-provisioned upload credential (43-256 ASCII characters).')
                secrets.save_password(config.upload_password_path if args.command == 'set-upload-token' else config.privacy_key_path, value)
                result = {'status': 'credential_protected'}
            elif args.command in {'collect', 'status', 'run'}:
                from collector.runtime import cycle, status, run
                if args.command == 'run':
                    run(config.path)
                    return 0
                result = cycle(config) if args.command == 'collect' else status(config)
            elif args.command == 'new-generation':
                from collector.generation import new_generation
                result = new_generation(config, args.generation_id, args.authorization)
            elif args.command == 're-export':
                from collector.recovery import re_export
                result = re_export(config,args.authorization)
            elif args.command == "check-config":
                result = {"status": "valid", "profile": PROFILE, "source_timezone": config.timezone or None,
                          "password_configured": config.password_path.is_file(), "cloud_uploads_enabled": config.upload_enabled}
            else:
                reader = SourceReader(config, secrets.load_password(config.password_path))
                if args.command == "test-connection":
                    result = reader.check()
                else:
                    records = reader.preview(args.table, args.after_id, args.limit, args.include_user_fields)
                    result = {"mode": "preview_only", "checkpoint_changed": False, "records": records}
            if args.command == "preview":
                encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                if len(encoded.encode("utf-8")) > config.max_output_bytes:
                    raise CollectorError("Preview exceeds max_output_bytes; request fewer records.")
                print(encoded)
                return 0
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except CollectorError as error:
        print(f"Collector: {error}", file=sys.stderr)
        return 1
    except (OSError, UnicodeError, EOFError):
        print("Collector: Local operation failed; check permissions, terminal encoding, and configuration.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Collector: Operation cancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
