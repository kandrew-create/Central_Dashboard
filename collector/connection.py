"""Explicit operator-triggered upload preflight; no data or checkpoint changes."""
import ssl
import time
from urllib.parse import urlsplit,urlunsplit

import httpx

from collector.errors import CollectorError
from collector.secrets import load_password
from shared.protocol import strict_json


def check_upload(config):
    if not config.upload_url or not config.source_id or not config.generation_id:
        raise CollectorError('Import server setup or save the upload URL, Source ID and Generation ID first.')
    try:token=load_password(config.upload_password_path)
    except CollectorError:
        raise CollectorError('Cannot unlock the upload credential. Import server setup or store its credential under this Windows account.') from None
    url=urlsplit(config.upload_url)
    endpoint=urlunsplit((url.scheme,url.netloc,'/v1/collector-check','',''))
    expected=dict(status='ready',source_id=config.source_id,generation_id=config.generation_id)
    try:
        with httpx.Client(verify=ssl.create_default_context(cafile=config.upload_ca_file or None),trust_env=False,follow_redirects=False,
                          timeout=httpx.Timeout(10,connect=5)) as client:
            with client.stream('POST',endpoint,json={k:expected[k] for k in ('source_id','generation_id')},
                               headers={'Authorization':'Bearer '+token,'Accept':'application/json'}) as response:
                if response.status_code==401:raise CollectorError('Server rejected the upload credential. Export and import the correct server setup.')
                if response.status_code==403:raise CollectorError('Server rejected the Source ID or active Generation ID. Check the selected source setup.')
                if response.status_code==404:raise CollectorError('The destination does not support connection testing. Update the Central Server package or check the upload address.')
                if response.status_code!=200 or response.headers.get('content-type','').split(';')[0]!='application/json' or response.headers.get('content-encoding','identity')!='identity':
                    raise CollectorError('The server did not return a valid connection-test response.')
                raw=bytearray()
                deadline=time.monotonic()+15
                for chunk in response.iter_bytes(chunk_size=1):
                    if len(raw)+len(chunk)>4096 or time.monotonic()>deadline:raise CollectorError('Server connection-test response exceeded its size or time limit.')
                    raw.extend(chunk)
                if strict_json(bytes(raw))!=expected:raise CollectorError('The connection-test response did not match this collector setup.')
        return dict(status='ready',upload_url=config.upload_url)
    except CollectorError:raise
    except (httpx.HTTPError,OSError,ValueError):
        raise CollectorError('Cannot verify the server connection. Check its hostname/IP, HTTPS port, certificate, network access and that the server is running.') from None
