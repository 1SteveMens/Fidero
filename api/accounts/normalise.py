"""Pure helpers: name normalisation (02 section 9.2) and keyed hashes used as
blind indexes (6.1). The SQL twin of normalise_name is acc_normalise_name()
in dbsql.py; both must give the same answer."""
import hashlib
import hmac
import re

from django.conf import settings

SUFFIXES = {"LTD", "LIMITED", "PLC", "CO", "COMPANY", "ENTERPRISE", "ENTERPRISES"}
HONORIFICS = {"MR", "MRS", "MS", "MISS", "DR", "PROF", "REV", "NANA", "TOGBE", "ALHAJI", "HAJIA"}  # [TO VERIFY]


def normalise_name(name: str) -> str:
    """Upper case, punctuation and double spaces removed, company suffixes and
    honorifics dropped. A pure function: no user can override its answer."""
    s = re.sub(r"[^A-Z0-9 ]+", " ", (name or "").upper())
    words = [w for w in s.split() if w not in SUFFIXES and w not in HONORIFICS]
    return " ".join(words)


def normalise_phone(phone: str) -> str:
    p = re.sub(r"[^0-9+]", "", phone or "")
    if p.startswith("00"):
        p = "+" + p[2:]
    return p


def bidx(value: str) -> str:
    key = (settings.SECRET_KEY + ":bidx").encode()
    return hmac.new(key, (value or "").encode(), hashlib.sha256).hexdigest()


def code_hash(salt: str, code: str) -> str:
    key = (settings.SECRET_KEY + ":otp").encode()
    return hmac.new(key, f"{salt}:{code}".encode(), hashlib.sha256).hexdigest()


def mask(value: str, keep=4) -> str:
    value = value or ""
    return ("•" * max(len(value) - keep, 0)) + value[-keep:]
