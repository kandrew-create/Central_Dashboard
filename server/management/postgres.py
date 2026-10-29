"""Supported Windows PostgreSQL binaries and safe external-program loading."""
from contextlib import contextmanager
import os
from pathlib import Path
import re
import subprocess
import sys

from collector.errors import CollectorError


SUPPORTED_MAJORS=(17,18)
REQUIRED_TOOLS=('postgres.exe','pg_ctl.exe','initdb.exe')


def default_postgres_bin(data_dir=None):
    majors=tuple(reversed(SUPPORTED_MAJORS))
    version_file=Path(data_dir)/'database/PG_VERSION' if data_dir is not None else None
    if version_file is not None and version_file.is_file():
        try:major=int(version_file.read_text().strip())
        except (OSError,ValueError):pass
        else:majors=(major,)
    root=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'PostgreSQL'
    for major in majors:
        candidate=root/str(major)/'bin'
        if all((candidate/name).is_file() for name in REQUIRED_TOOLS):return candidate
    return root/str(majors[0])/'bin'


@contextmanager
def external_program():
    """PostgreSQL must load its own DLLs, not the frozen launcher's runtime."""
    frozen=getattr(sys,'frozen',False)
    if frozen:
        import win32api
        win32api.SetDllDirectory(None)
    try:
        yield
    finally:
        if frozen:win32api.SetDllDirectory(str(sys._MEIPASS))


def postgres_major(bin_dir):
    bin_dir=Path(bin_dir)
    if not bin_dir.is_absolute() or any(not (bin_dir/name).is_file() for name in REQUIRED_TOOLS):
        raise CollectorError('Select a PostgreSQL 17 or 18 bin folder containing postgres.exe, pg_ctl.exe and initdb.exe.')
    versions=[]
    for name in REQUIRED_TOOLS:
        try:
            with external_program():
                result=subprocess.run([str(bin_dir/name),'--version'],capture_output=True,text=True,
                                      timeout=5,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            match=re.search(r'\(PostgreSQL\)\s+(\d+)(?:\.|\s|$)',result.stdout)
            if result.returncode or not match:raise ValueError()
            major=int(match.group(1))
        except (OSError,ValueError,subprocess.SubprocessError):
            raise CollectorError(f'Cannot verify {name}. Select working PostgreSQL 17 or 18 binaries.') from None
        if major not in SUPPORTED_MAJORS:
            raise CollectorError(f'PostgreSQL {major} is not supported. Select PostgreSQL 17 or 18 binaries.')
        versions.append(major)
    if len(set(versions))!=1:
        raise CollectorError('The selected PostgreSQL tools have different major versions. Select one complete PostgreSQL 17 or 18 bin folder.')
    return versions[0]
