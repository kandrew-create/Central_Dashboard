from dataclasses import dataclass
import json
import ipaddress
import os
import re
from pathlib import Path
import sys

from collector.errors import CollectorError
from collector.secrets import restrict_access,write_private_file


def settings_path():
    return Path(os.environ.get('PROGRAMDATA',r'C:\ProgramData'))/'Linker'/'CentralServer'/'manager.json'


@dataclass(frozen=True)
class ServerSettings:
    data_dir: Path
    postgres_bin: Path=Path(r'C:\Program Files\PostgreSQL\17\bin')
    database_port: int=55441
    https_port: int=8443
    mode: str='local'
    listen_address: str='127.0.0.1'
    server_host: str='localhost'

    @property
    def upload_url(self):
        return f'https://{self.server_host}:{self.https_port}/v1/uploads'

    @property
    def health_host(self):
        return '127.0.0.1' if self.listen_address=='0.0.0.0' else self.listen_address

    def validate_network(self):
        if self.mode not in {'local','network'}:
            raise CollectorError('Select Local testing or Network server mode.')
        try:address=ipaddress.IPv4Address(self.listen_address)
        except (ValueError,TypeError):
            raise CollectorError('Listen address must be an IPv4 address; use 0.0.0.0 for all network adapters.') from None
        if address.is_multicast:
            raise CollectorError('A multicast listen address is not supported.')
        host=self.server_host
        if not isinstance(host,str) or not host or len(host)>253 or host!=host.strip() or host!=host.lower():
            raise CollectorError('Enter the central PC hostname or IPv4 address in lowercase, without https://, a port or a path.')
        try:destination=ipaddress.ip_address(host)
        except ValueError:
            if not re.fullmatch(r'(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*',host) or all(c in '0123456789.' for c in host):
                raise CollectorError('Enter a valid central PC hostname or IPv4 address.') from None
            destination=None
        if destination and (destination.version!=4 or destination.is_unspecified or destination.is_multicast):
            raise CollectorError('Use a reachable IPv4 address or hostname for the central PC.')
        loopback=host=='localhost' or host.endswith('.localhost') or bool(destination and destination.is_loopback)
        if self.mode=='local' and (self.listen_address!='127.0.0.1' or host!='localhost'):
            raise CollectorError('Local testing uses listen address 127.0.0.1 and server hostname localhost.')
        if self.mode=='network' and (address.is_loopback or loopback):
            raise CollectorError('Network server mode needs a LAN listen address and the central PC hostname/IP, not localhost.')
        return self

    def validate(self):
        self.validate_network()
        if not self.data_dir.is_absolute() or self.data_dir.is_symlink():
            raise CollectorError('Choose an absolute, dedicated server data folder without symbolic links.')
        if not self.postgres_bin.is_absolute() or any(not (self.postgres_bin/name).is_file() for name in ('pg_ctl.exe','initdb.exe')):
            raise CollectorError('Select the PostgreSQL 17 bin folder containing pg_ctl.exe and initdb.exe.')
        if any(type(port) is not int or not 1024<=port<=65535 for port in (self.database_port,self.https_port)) or self.database_port==self.https_port:
            raise CollectorError('Choose distinct server ports from 1024 to 65535.')
        if self.data_dir.exists() and any(self.data_dir.iterdir()) and not (self.data_dir/'credentials.dpapi').is_file():
            raise CollectorError('This folder contains other files. Choose a new dedicated folder or an existing Central Server data folder.')
        if (self.data_dir/'database/PG_VERSION').exists() and (self.data_dir/'database/PG_VERSION').read_text().strip()!='17':
            raise CollectorError('This local server package requires a PostgreSQL 17 data directory.')
        return self

    def document(self):
        return dict(version=2,data_dir=str(self.data_dir),postgres_bin=str(self.postgres_bin),
                    database_port=self.database_port,https_port=self.https_port,mode=self.mode,
                    listen_address=self.listen_address,server_host=self.server_host)


def load_settings(path=None):
    path=Path(path or settings_path())
    if path.is_file():
        try:
            if path.stat().st_size>16384: raise ValueError()
            value=json.loads(path.read_text(encoding='utf-8'))
            original={'version','data_dir','postgres_bin','database_port','https_port'}
            version=value.get('version')
            expected=original if version==1 else original|{'mode','listen_address','server_host'}
            if set(value)!=expected or type(version) is not int or version not in {1,2}:
                raise ValueError()
            return ServerSettings(Path(value['data_dir']),Path(value['postgres_bin']),value['database_port'],value['https_port'],
                                  value.get('mode','local'),value.get('listen_address','127.0.0.1'),value.get('server_host','localhost')).validate_network()
        except (OSError,ValueError,TypeError):
            raise CollectorError('Cannot read Central Server manager settings.') from None
    legacy=Path(__file__).resolve().parents[2]/'.tools/local-server'
    data_dir=legacy if not getattr(sys,'frozen',False) and (legacy/'credentials.dpapi').exists() else path.parent/'data'
    return ServerSettings(data_dir.resolve())


def save_settings(settings,path=None):
    settings.validate()
    path=Path(path or settings_path())
    if path.parent.is_symlink() or path.is_symlink():
        raise CollectorError('Manager settings must not use symbolic links.')
    path.parent.mkdir(parents=True,exist_ok=True)
    restrict_access(path.parent)
    write_private_file(path,json.dumps(settings.document(),indent=2).encode())
