"""Ports and fake adapters for ACC (ADR-10). Each runs the whole workflow
offline; real adapters replace them one by one through settings.TENMINA
["ADAPTERS"] (ports: one_time_codes, identity_check, national_id)."""
import hashlib
import json
import logging

from django.conf import settings

log = logging.getLogger(__name__)


class FakeOtpSender:
    """Logs each one-time code instead of sending it. In dev and test the
    code 000000 is also accepted, so demos and app builds can sign up."""

    MASTER_CODE = "000000"
    sent: list = []  # (channel, destination, purpose, code), newest last; for tests and local demos

    def send(self, *, channel: str, destination: str, code: str, purpose: str) -> bool:
        log.info("one-time code %s for %s via %s: %s", purpose, destination, channel, code)
        type(self).sent.append((channel, destination, purpose, code))
        del type(self).sent[:-200]
        return True

    def accepts_master_code(self) -> bool:
        return getattr(settings, "ENVIRONMENT", "dev") in ("dev", "test")

    @classmethod
    def last_code(cls, destination, purpose=None):
        for ch, dest, pur, code in reversed(cls.sent):
            if dest == destination and (purpose is None or pur == purpose):
                return code
        return None


class FakeIdentityCheckProvider:
    """The client's own identity check (FR-ACC-004, IF-03). Deterministic by
    the last digit of the document number: 0 failed, 5 inconclusive,
    9 unavailable, anything else passed. Keeps no document image."""

    name = "fake-identity-provider"

    def check(self, *, person, document_type: str, document_number: str, country) -> dict:
        last = (document_number.strip() or "1")[-1]
        result = {"0": "failed", "5": "inconclusive", "9": "unavailable"}.get(last, "passed")
        ref = None
        if result != "unavailable":
            ref = "IDP-" + hashlib.sha256(f"{person.pk}:{document_number}".encode()).hexdigest()[:12].upper()
        return {"result": result, "reference": ref}


class FakeNationalIdProvider:
    """National identity system through an approved channel (IF-03, RUL-31,
    02 section 9.4). The fake answers by number:

    - numbers in REGISTRY return that name (so a different name is a no_match);
    - numbers ending in -0 are not found;
    - numbers ending in -9, or any number while `down` is True, are unavailable;
    - any other number returns the name it was asked about.

    Like a real response it carries a photo and fingerprint fields; the
    adapter drops every biometric field before the result reaches the
    application, and only a hash of the raw response is kept.
    """

    BIOMETRIC_FIELDS = ("photo", "portrait", "fingerprint", "fingerprints", "face", "face_template", "selfie",
                        "signature_image", "biometrics")
    REGISTRY = {
        "GHA-700000001-1": "Kwabena Owusu",
        "GHA-700000002-2": "Akua Asantewaa",
    }
    down = False  # tests switch the service off

    def verify(self, *, id_number: str, name: str, country) -> dict:
        number = id_number.strip().upper()
        if type(self).down or number.endswith("-9"):
            return {"status": "unavailable"}
        if number.endswith("-0"):
            raw = {"status": "not_found", "transaction_id": self._ref(number, "NF")}
        else:
            raw = {"status": "found", "transaction_id": self._ref(number, "OK"),
                   "name": self.REGISTRY.get(number, name), "photo": "base64-not-kept",
                   "fingerprint": "template-not-kept", "date_of_birth": "1970-01-01"}
        return self._clean(raw)

    def _ref(self, number, tag):
        import uuid

        return f"NIA-{tag}-{uuid.uuid4().hex[:10].upper()}"

    def _clean(self, raw: dict) -> dict:
        digest = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
        clean = {k: v for k, v in raw.items() if k not in self.BIOMETRIC_FIELDS}
        clean["response_sha256"] = digest
        return clean
