"""Canonical JSON (RFC 8785) and manifest signatures (02 section 8.4).

The app signs the canonical bytes of the manifest with its hardware key:
ES256 (ECDSA P-256 with SHA-256, DER signature, base64url) from Android
Keystore or the Secure Enclave, or EdDSA (Ed25519) where a platform offers it.
"""
import base64
import hashlib
import json
import math

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519

ALGORITHMS = ("ES256", "EdDSA")


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def b64decode_any(s: str) -> bytes:
    s = (s or "").strip()
    pad = "=" * (-len(s) % 4)
    if "-" in s or "_" in s:
        return base64.urlsafe_b64decode(s + pad)
    return base64.b64decode(s + pad)


def _number(n) -> str:
    if isinstance(n, bool):
        return "true" if n else "false"
    if isinstance(n, int):
        return str(n)
    if math.isnan(n) or math.isinf(n):
        raise ValueError("NaN and infinity are not allowed in a manifest")
    if n.is_integer() and abs(n) < 1e21:
        return str(int(n))
    r = repr(n)
    if "e" in r:  # ECMAScript style exponent: 1e-07 -> 1e-7, 1e+21 -> 1e+21
        mant, exp = r.split("e")
        sign = "-" if exp.startswith("-") else "+"
        r = f"{mant}e{sign}{int(exp.lstrip('+-'))}"
    return r


def canonical(value) -> bytes:
    """RFC 8785 JSON Canonicalization Scheme (keys sorted by UTF-16 code units)."""

    def enc(v):
        if v is None:
            return "null"
        if isinstance(v, bool) or isinstance(v, (int, float)):
            return _number(v)
        if isinstance(v, str):
            return json.dumps(v, ensure_ascii=False)
        if isinstance(v, (list, tuple)):
            return "[" + ",".join(enc(x) for x in v) + "]"
        if isinstance(v, dict):
            items = sorted(v.items(), key=lambda kv: kv[0].encode("utf-16-be"))
            return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + enc(x) for k, x in items) + "}"
        raise TypeError(f"Cannot canonicalise {type(v).__name__}")

    return enc(value).encode("utf-8")


def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load_public_key(text: str):
    """PEM, or base64/base64url DER SubjectPublicKeyInfo."""
    text = (text or "").strip()
    if text.startswith("-----BEGIN"):
        return serialization.load_pem_public_key(text.encode())
    return serialization.load_der_public_key(b64decode_any(text))


def key_algorithm(key) -> str:
    if isinstance(key, ec.EllipticCurvePublicKey):
        if key.curve.name != "secp256r1":
            raise ValueError("Only P-256 ECDSA keys are accepted")
        return "ES256"
    if isinstance(key, ed25519.Ed25519PublicKey):
        return "EdDSA"
    raise ValueError("Unsupported key type")


def spki_b64(key) -> str:
    return base64.b64encode(key.public_bytes(serialization.Encoding.DER,
                                             serialization.PublicFormat.SubjectPublicKeyInfo)).decode()


def verify(public_key_text: str, alg: str, data: bytes, signature: str) -> bool:
    try:
        key = load_public_key(public_key_text)
        sig = b64decode_any(signature)
        if alg == "ES256" and isinstance(key, ec.EllipticCurvePublicKey):
            key.verify(sig, data, ec.ECDSA(hashes.SHA256()))
            return True
        if alg == "EdDSA" and isinstance(key, ed25519.Ed25519PublicKey):
            key.verify(sig, data)
            return True
        return False
    except (InvalidSignature, ValueError, TypeError):
        return False


def sign(private_key, data: bytes) -> str:
    """For the development phone and tests only; real signing happens on the device."""
    if isinstance(private_key, ec.EllipticCurvePrivateKey):
        return b64url(private_key.sign(data, ec.ECDSA(hashes.SHA256())))
    return b64url(private_key.sign(data))
