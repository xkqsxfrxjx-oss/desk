"""AES-256-GCM for published JSON. Key = HKDF-SHA256(APP_TOKEN, salt=b"desk-v1", info=b"data")."""
import base64, json, os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
def _key(token): return HKDF(hashes.SHA256(), 32, b"desk-v1", b"data").derive(token.encode())
def encrypt(obj, token):
    iv = os.urandom(12)
    ct = AESGCM(_key(token)).encrypt(iv, json.dumps(obj, separators=(",", ":")).encode(), None)
    return {"v": 1, "iv": base64.b64encode(iv).decode(), "ct": base64.b64encode(ct).decode()}
def decrypt(env, token):
    return json.loads(AESGCM(_key(token)).decrypt(base64.b64decode(env["iv"]), base64.b64decode(env["ct"]), None))
def secrets_file(path=os.path.join(os.path.dirname(__file__), ".secrets")):
    return dict(l.strip().split("=", 1) for l in open(path) if "=" in l)
