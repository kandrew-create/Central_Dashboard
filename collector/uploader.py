"""Fixed-destination HTTPS delivery; only a matching durable receipt commits state."""
import random
import ssl
import time

import httpx

from collector.errors import CollectorError
from collector.secrets import load_password
from shared.protocol import ProtocolError, strict_json


def deliver(config, state, client=None):
    pending = state.pending()
    if not pending or pending['retry_at'] > time.time():
        return False
    if not config.upload_enabled or not config.upload_url.startswith('https://'):
        return False
    try:
        token = load_password(config.upload_password_path)
    except CollectorError:
        raise CollectorError('Cannot unlock the upload credential. Store the server-provisioned token under the collector Windows account.') from None
    owned = client is None
    try:
        client = client or httpx.Client(verify=ssl.create_default_context(cafile=config.upload_ca_file or None), follow_redirects=False, trust_env=False,
                                      timeout=httpx.Timeout(20, connect=5), limits=httpx.Limits(max_connections=1))
    except (OSError,ValueError):
        raise CollectorError('Cannot load the configured upload CA file. Check the local certificate path and permissions.') from None
    failure = None
    permanent = False
    try:
        with client.stream('POST', config.upload_url, content=pending['payload'],
                           headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json', 'Accept': 'application/json'},
                           follow_redirects=False) as response:
            if response.status_code != 200:
                permanent = response.status_code not in {408, 429, 500, 502, 503, 504}
                raise CollectorError('Upload rejected by server; check credentials, destination, schema, and server status.')
            if response.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
                raise CollectorError('Upload receipt has an invalid content type.')
            if response.headers.get('content-encoding', 'identity').lower() != 'identity':
                raise CollectorError('Compressed upload receipts are not accepted.')
            raw = bytearray()
            deadline = time.monotonic() + 20
            for chunk in response.iter_bytes(chunk_size=1024):
                if len(raw) + len(chunk) > 4096 or time.monotonic() > deadline:
                    raise CollectorError('Upload receipt exceeded its size or time limit.')
                raw.extend(chunk)
            receipt = strict_json(bytes(raw))
            if not isinstance(receipt, dict):
                raise CollectorError('Upload receipt must be a fixed JSON object.')
            state.confirm(receipt)
        with state.transaction():
            state.put('latest_error', None)
        return True
    except (httpx.HTTPError, ProtocolError, CollectorError) as error:
        failure = str(error) if isinstance(error, CollectorError) else 'Upload TLS, transport, or JSON validation failed; pending batch retained.'
        permanent = permanent or isinstance(error, (ProtocolError, CollectorError))
    finally:
        if owned:
            client.close()
    delay = 3600 if permanent else min(3600, 10 * 2 ** min(pending['attempts'], 8)) * random.uniform(1, 1.2)
    with state.transaction():
        state.db.execute('UPDATE queue SET attempts=attempts+1,retry_at=? WHERE sequence=?', (time.time() + delay, pending['sequence']))
        state.put('latest_error', failure)
    raise CollectorError(failure)
