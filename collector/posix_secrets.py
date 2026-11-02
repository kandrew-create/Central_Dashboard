"""Linux private files and authenticated encryption using a separately mounted key."""
import os
from pathlib import Path
import stat
import tempfile

from cryptography.fernet import Fernet

from collector.errors import CollectorError


def restrict_access(path):
    path = Path(path)
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid():
        raise CollectorError('Collector files must be owned by this account and must not use symbolic links.')
    path.chmod(0o700 if stat.S_ISDIR(info.st_mode) else 0o600)


def create_key(path):
    """Create exclusively; replacing a key would make existing credentials unreadable."""
    path = Path(path)
    with path.open('xb') as stream:
        restrict_access(path)
        stream.write(Fernet.generate_key())
        stream.flush()
        os.fsync(stream.fileno())


def _cipher():
    try:
        path = Path(os.environ['COLLECTOR_SECRET_KEY_FILE'])
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > 128):
            raise ValueError()
        return Fernet(path.read_bytes().strip())
    except (KeyError, OSError, ValueError):
        raise CollectorError('Set COLLECTOR_SECRET_KEY_FILE to a private key file owned by the collector account (mode 600). Preserve the existing key; never regenerate it to bypass an unlock error.') from None


def write_private_file(path, content):
    path = Path(path)
    restrict_access(path.parent)
    if path.is_symlink():
        raise CollectorError('Collector files must not use symbolic links.')
    temporary = None
    try:
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix='.private-')
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def save_password(path, password):
    if not isinstance(password, str) or not password or len(password) > 4096 or '\x00' in password:
        raise CollectorError('Enter a nonempty credential of at most 4096 characters.')
    cipher = _cipher()
    path = Path(path)
    path.parent.mkdir(mode=0o700, exist_ok=True)
    write_private_file(path, cipher.encrypt(password.encode('utf-8')))


def load_password(path):
    cipher = _cipher()
    try:
        path = Path(path)
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > 32768):
            raise ValueError()
        password = cipher.decrypt(path.read_bytes()).decode('utf-8')
        if not password or len(password) > 4096 or '\x00' in password:
            raise ValueError()
        return password
    except Exception:
        raise CollectorError('Cannot unlock the credential. Check the collector account, private file permissions and original encryption key.') from None
