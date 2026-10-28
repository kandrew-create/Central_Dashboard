"""Windows current-user DPAPI and private ACLs; no plaintext fallback."""
import os
from pathlib import Path
import tempfile

from collector.errors import CollectorError

CRYPTPROTECT_UI_FORBIDDEN = 0x1


def _windows():
    if os.name != "nt":
        raise CollectorError("Protected setup requires Windows; no plaintext secret fallback is supported.")
    try:
        import win32api
        import win32con
        import win32crypt
        import win32security
    except ImportError:
        raise CollectorError("Install the collector dependencies, including pywin32.") from None
    return win32api, win32con, win32crypt, win32security


def restrict_access(path):
    api, con, _crypt, security = _windows()
    try:
        from ntsecuritycon import FILE_ALL_ACCESS
        token = security.OpenProcessToken(api.GetCurrentProcess(), con.TOKEN_QUERY)
        try:
            owner = security.GetTokenInformation(token, security.TokenUser)[0]
        finally:
            token.Close()
        system = security.CreateWellKnownSid(security.WinLocalSystemSid, None)
        acl = security.ACL()
        inherit = (con.OBJECT_INHERIT_ACE | con.CONTAINER_INHERIT_ACE) if Path(path).is_dir() else 0
        for sid in (owner, system):
            acl.AddAccessAllowedAceEx(security.ACL_REVISION, inherit, FILE_ALL_ACCESS, sid)
        security.SetNamedSecurityInfo(str(path), security.SE_FILE_OBJECT,
            security.DACL_SECURITY_INFORMATION | security.PROTECTED_DACL_SECURITY_INFORMATION,
            None, None, acl, None)
    except Exception:
        raise CollectorError("Cannot restrict local file permissions; check account ownership.") from None


def initialize(path, content):
    """Use a new dedicated directory; never change ACLs on an existing shared folder."""
    _windows()
    path = Path(path).resolve()
    try:
        path.parent.mkdir(parents=True, exist_ok=False)
        restrict_access(path.parent)
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        restrict_access(path)
    except OSError:
        raise CollectorError("Setup needs a new, writable collector directory; existing directories are preserved.") from None


def save_password(path, password):
    _api, con, crypt, _security = _windows()
    if not isinstance(password, str) or not password or len(password) > 4096 or "\x00" in password:
        raise CollectorError("Enter a nonempty database password of at most 4096 characters.")
    path = Path(path)
    temporary = None
    try:
        path.parent.mkdir(exist_ok=True)
        restrict_access(path.parent)
        protected = crypt.CryptProtectData(password.encode("utf-8"), "SCADA collector database password",
            None, None, None, CRYPTPROTECT_UI_FORBIDDEN)
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".password-")
        with os.fdopen(descriptor, "wb") as stream:
            restrict_access(temporary)
            stream.write(protected)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    except CollectorError:
        raise
    except Exception:
        raise CollectorError("Cannot protect/save the password under the current Windows account.") from None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def load_password(path):
    _api, con, crypt, _security = _windows()
    try:
        path = Path(path)
        if path.stat().st_size > 32768:
            raise ValueError("oversized secret")
        _description, plaintext = crypt.CryptUnprotectData(path.read_bytes(), None, None, None,
            CRYPTPROTECT_UI_FORBIDDEN)
        password = plaintext.decode("utf-8")
        if not password or "\x00" in password:
            raise ValueError("invalid secret")
        return password
    except Exception:
        raise CollectorError("Cannot unlock the database password; run set-password under this Windows account.") from None


def write_private_file(path, content):
    """Replace a local settings file atomically, with its private ACL in place first."""
    _windows()
    temporary = None
    try:
        path = Path(path)
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".settings-")
        with os.fdopen(descriptor, "wb") as stream:
            restrict_access(temporary)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    except CollectorError:
        raise
    except OSError:
        raise CollectorError("Cannot save settings; check local file permissions.") from None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
