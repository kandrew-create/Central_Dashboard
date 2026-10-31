"""Local Linux credential encryption; key and ciphertext require private ownership."""
import json
import os
from pathlib import Path
import stat
import tempfile

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from collector.errors import CollectorError


HEADER = b'LINKER-LINUX-VAULT-1\0'


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def private_directory(path):
    path = Path(path)
    if os.name != 'posix' or path.is_symlink():
        raise CollectorError('Use a private Linux directory for Docker manager credentials.')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise CollectorError('The Docker manager credential directory must be owned by this account with mode 0700.')
    return path


def private_read(path, limit=131072):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > limit):
            raise CollectorError('Docker manager credentials must be private regular files owned by this account.')
        return stream.read(limit + 1)


def private_write(path, content):
    path = Path(path)
    if path.is_symlink():
        raise CollectorError('A credential file cannot be a symbolic link.')
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix='.vault-')
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


class LinuxVault:
    def __init__(self, directory):
        self.directory = Path(directory)

    def _key(self, create=False):
        private_directory(self.directory)
        key_path = self.directory / 'vault.key'
        if create and not key_path.exists():
            if any(self.directory.glob('*.vault')):
                raise CollectorError('The credential key is missing. Preserve the existing vault and restore its key.')
            try:
                descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(descriptor, 'wb') as stream:
                    stream.write(os.urandom(32))
                    stream.flush()
                    os.fsync(stream.fileno())
                sync_directory(self.directory)
        try:
            key = private_read(key_path, 32)
        except OSError:
            raise CollectorError('Cannot read the private Docker manager credential key. Preserve the existing vault.') from None
        if len(key) != 32:
            raise CollectorError('The Docker manager credential key is invalid. Restore it before continuing.')
        return key

    def save(self, path, document):
        key = self._key(create=True)
        nonce = os.urandom(12)
        path = Path(path)
        encrypted = AESGCM(key).encrypt(nonce, json.dumps(document).encode(), path.stem.encode())
        private_write(path, HEADER + nonce + encrypted)

    def load(self, path):
        key = self._key()
        path = Path(path)
        try:
            content = private_read(path)
            if not content.startswith(HEADER) or len(content) < len(HEADER) + 28:
                raise ValueError()
            body = content[len(HEADER):]
            decoded = AESGCM(key).decrypt(body[:12], body[12:], path.stem.encode())
            result = json.loads(decoded)
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except (OSError, ValueError, InvalidTag):
            raise CollectorError('Cannot unlock this Docker manager credential. Check its key and file integrity.') from None
