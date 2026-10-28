"""Private commissioning CA, retained across leaf renewal and address changes."""
from datetime import datetime,timedelta,timezone
import ipaddress

from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID,ExtendedKeyUsageOID

from collector.errors import CollectorError
from collector.secrets import write_private_file


def names_for(host='localhost',listen_address='127.0.0.1'):
    names={host,'localhost','127.0.0.1'}
    if listen_address!='0.0.0.0':names.add(listen_address)
    result=[]
    for name in sorted(names):
        try:result.append(x509.IPAddress(ipaddress.ip_address(name)))
        except ValueError:result.append(x509.DNSName(name))
    return result


def validate_certificate(directory,host='localhost',listen_address='127.0.0.1',renew_before=0):
    try:
        now=datetime.now(timezone.utc)
        leaf=x509.load_pem_x509_certificate((directory/'localhost.pem').read_bytes())
        ca=x509.load_pem_x509_certificate((directory/'ca.pem').read_bytes())
        key=serialization.load_pem_private_key((directory/'localhost-key.pem').read_bytes(),None)
        leaf.verify_directly_issued_by(ca)
        actual=leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        if any(name not in actual for name in names_for(host,listen_address)):
            raise ValueError()
        if not leaf.not_valid_before_utc<=now<leaf.not_valid_after_utc-timedelta(days=renew_before) or not ca.not_valid_before_utc<=now<ca.not_valid_after_utc:
            raise ValueError()
        if not ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
            raise ValueError()
        if ExtendedKeyUsageOID.SERVER_AUTH not in leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value:
            raise ValueError()
        if key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)!=leaf.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo):
            raise ValueError()
    except Exception:
        raise CollectorError('Start the server with the saved mode/address to prepare a valid matching HTTPS certificate before exporting setup.') from None


def ensure_certificates(directory,host='localhost',listen_address='127.0.0.1'):
    try:
        validate_certificate(directory,host,listen_address,renew_before=1)
        return
    except CollectorError:pass
    now=datetime.now(timezone.utc)
    try:
        ca=x509.load_pem_x509_certificate((directory/'ca.pem').read_bytes())
        root_key=serialization.load_pem_private_key((directory/'ca-key.pem').read_bytes(),None)
        if not ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca or ca.not_valid_after_utc<now+timedelta(days=31):raise ValueError()
        if root_key.public_key().public_numbers()!=ca.public_key().public_numbers():raise ValueError()
    except (OSError,ValueError,TypeError,x509.ExtensionNotFound):
        root_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Linker commissioning CA')])
        ca=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(root_key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(root_key.public_key()),critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()),critical=False)
            .add_extension(x509.KeyUsage(digital_signature=True,content_commitment=False,key_encipherment=False,data_encipherment=False,key_agreement=False,key_cert_sign=True,crl_sign=True,encipher_only=None,decipher_only=None),critical=True)
            .sign(root_key,hashes.SHA256()))
        write_private_file(directory/'ca-key.pem',root_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        write_private_file(directory/'ca.pem',ca.public_bytes(serialization.Encoding.PEM))
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    leaf=(x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,host[:64])]))
          .issuer_name(ca.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=90))
          .add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),critical=False)
          .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()),critical=False)
          .add_extension(x509.KeyUsage(digital_signature=True,content_commitment=False,key_encipherment=True,data_encipherment=False,key_agreement=False,key_cert_sign=False,crl_sign=False,encipher_only=None,decipher_only=None),critical=True)
          .add_extension(x509.SubjectAlternativeName(names_for(host,listen_address)),critical=False)
          .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),critical=False).sign(root_key,hashes.SHA256()))
    write_private_file(directory/'localhost-key.pem',key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    write_private_file(directory/'localhost.pem',leaf.public_bytes(serialization.Encoding.PEM)+ca.public_bytes(serialization.Encoding.PEM))
    validate_certificate(directory,host,listen_address)
