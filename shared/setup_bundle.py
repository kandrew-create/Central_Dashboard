"""Password-encrypted, locally selected collector provisioning files.

Only destination, credential and identity are transferred. Extraction settings
and source database credentials always remain under local collector control.
"""
import base64
from datetime import datetime,timezone
import json
import os
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from shared.protocol import canonical_bytes,strict_json,uuid_text

FORMAT='linker-collector-setup-v1'
MAX_FILE_BYTES=65536


class SetupError(ValueError):
    pass


def validate_setup(value):
    expected={'version','source_id','generation_id','upload_url','upload_token','ca_certificate_pem','source_name','local_test_only'}
    if not isinstance(value,dict) or set(value)!=expected or type(value['version']) is not int or value['version']!=1:
        raise SetupError('Unsupported collector setup file.')
    try:
        uuid_text(value['source_id']); uuid_text(value['generation_id'])
        url=urlsplit(value['upload_url'])
        if url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment or (url.port is not None and url.port<1):
            raise ValueError()
        if type(value['local_test_only']) is not bool:
            raise ValueError()
        if value['local_test_only'] and url.hostname not in {'localhost','127.0.0.1','::1'}:
            raise ValueError()
        token=value['upload_token']
        if not isinstance(token,str) or not token.isascii() or not 43<=len(token)<=256:
            raise ValueError()
        if not isinstance(value['source_name'],str) or not 1<=len(value['source_name'])<=255:
            raise ValueError()
        pem=value['ca_certificate_pem']
        if not isinstance(pem,str) or len(pem.encode())>16384:
            raise ValueError()
        if pem:
            cert=x509.load_pem_x509_certificate(pem.encode())
            if not cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca or cert.not_valid_after_utc<=datetime.now(timezone.utc):
                raise ValueError()
    except (ValueError,TypeError,AttributeError,x509.ExtensionNotFound):
        raise SetupError('Invalid collector identity, destination, credential or CA certificate.') from None
    return value


def _key(password,salt):
    if not isinstance(password,str) or not 12<=len(password)<=1024:
        raise SetupError('Use a setup-file password of at least 12 characters.')
    return Scrypt(salt=salt,length=32,n=16384,r=8,p=1).derive(password.encode('utf-8'))


def encode_setup(value,password):
    validate_setup(value)
    salt,nonce=os.urandom(16),os.urandom(12)
    encrypted=AESGCM(_key(password,salt)).encrypt(nonce,canonical_bytes(value),FORMAT.encode())
    envelope={'format':FORMAT,'salt':base64.b64encode(salt).decode(),'nonce':base64.b64encode(nonce).decode(),
              'ciphertext':base64.b64encode(encrypted).decode()}
    result=canonical_bytes(envelope)
    if len(result)>MAX_FILE_BYTES:
        raise SetupError('Collector setup file exceeds its size limit.')
    return result


def decode_setup(data,password):
    if not isinstance(data,bytes) or len(data)>MAX_FILE_BYTES:
        raise SetupError('Collector setup file exceeds its size limit.')
    try:
        envelope=strict_json(data)
        if not isinstance(envelope,dict) or set(envelope)!={'format','salt','nonce','ciphertext'} or envelope['format']!=FORMAT:
            raise ValueError()
        salt,nonce,encrypted=(base64.b64decode(envelope[k],validate=True) for k in ('salt','nonce','ciphertext'))
        if len(salt)!=16 or len(nonce)!=12 or not 16<=len(encrypted)<=MAX_FILE_BYTES:
            raise ValueError()
        plaintext=AESGCM(_key(password,salt)).decrypt(nonce,encrypted,FORMAT.encode())
        return validate_setup(strict_json(plaintext))
    except SetupError:
        raise
    except (ValueError,TypeError,KeyError,InvalidTag,UnicodeError,RecursionError):
        raise SetupError('Cannot unlock this setup file. Check the password and file integrity.') from None
