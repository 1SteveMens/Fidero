"""Ports for the field app server (ADR-10), each with a fake so the flow runs offline.

- mobile_attestation: FakeAttestation stands in for Android key attestation with Play Integrity
  and for Apple App Attest (8.2). The real adapters check the certificate chain to Google's
  attestation root, the Play Integrity verdict from Google's server, or the App Attest object
  to Apple's root.
- mobile_upload_staging: LocalUploadStaging holds uploaded bytes until `complete` (the S3
  quarantine prefix in production).
"""
import hashlib
from pathlib import Path

from django.conf import settings

from .crypto import b64decode_any

FIELD_APP_IDS = {"android": "com.tenmina.field", "ios": "com.tenmina.field"}  # [TO VERIFY]
STORE_BUILDS = {"store", "testflight", "play_internal"}
GOOD_ANDROID_VERDICTS = {"MEETS_STRONG_INTEGRITY", "MEETS_DEVICE_INTEGRITY"}


class FakeAttestation:
    """Deterministic stand-in. The attestation the app sends is a JSON object:

    android: {"challenge", "build": "store"|"play_internal"|"sideloaded"|"resigned"|"development",
              "key_security": "strongbox"|"tee"|"software", "device_integrity": "MEETS_DEVICE_INTEGRITY",
              "app_recognized": true, "emulator": false, "signing_digest": "..."}
    ios:     {"challenge", "build": "store"|"testflight"|"development", "environment": "production",
              "key_id": "...", "counter": 0, "key_sha256": "<sha256 of the public key DER>"}
    """

    def verify(self, *, platform, challenge, public_key, attestation, app_id) -> dict:
        a = attestation or {}
        fail = []
        if a.get("challenge") != challenge:
            fail.append("challenge_mismatch")
        if a.get("build", "store") not in STORE_BUILDS:
            fail.append("not_a_store_build")
        if a.get("emulator"):
            fail.append("emulator")
        if app_id != FIELD_APP_IDS.get(platform):
            fail.append("wrong_app")
        spki_sha = hashlib.sha256(b64decode_any(public_key)).hexdigest() if public_key else ""
        if platform == "android":
            security = a.get("key_security", "tee")
            if security not in ("strongbox", "tee", "software"):
                fail.append("unknown_key_security")
            if a.get("device_integrity", "MEETS_DEVICE_INTEGRITY") not in GOOD_ANDROID_VERDICTS:
                fail.append("device_integrity")
            if not a.get("app_recognized", True):
                fail.append("app_not_recognized")
            verdict = {"device_integrity": a.get("device_integrity", "MEETS_DEVICE_INTEGRITY"),
                       "app_recognized": a.get("app_recognized", True), "licensed": True}
            counter, key_id = None, ""
        else:
            security = "secure_enclave"
            if a.get("environment", "production") != "production":
                fail.append("development_environment")
            if int(a.get("counter", 0)) != 0:
                fail.append("counter_not_zero")
            if a.get("key_sha256") and a["key_sha256"] != spki_sha:
                fail.append("key_not_attested")
            verdict = {"environment": a.get("environment", "production")}
            counter, key_id = 0, a.get("key_id", "")
        return {"ok": not fail, "reasons": fail, "key_security": security, "verdict": verdict,
                "signing_digest": a.get("signing_digest", ""), "counter": counter, "app_attest_key_id": key_id}

    def check(self, device, payload: dict) -> dict:
        """A later Play Integrity token or App Attest assertion (8.2 step 7)."""
        p = payload or {}
        fail = []
        if p.get("emulator"):
            fail.append("emulator")
        if device.platform == "android":
            if p.get("device_integrity", "MEETS_DEVICE_INTEGRITY") not in GOOD_ANDROID_VERDICTS:
                fail.append("device_integrity")
            counter = None
        else:
            counter = int(p.get("counter", -1))
            if device.app_attest_counter is not None and counter <= device.app_attest_counter:
                fail.append("counter_not_increasing")
        return {"ok": not fail, "reasons": fail, "verdict": p, "counter": counter}


class LocalUploadStaging:
    """Quarantine for uploaded bytes until the server checks them (overwritable, then deleted)."""

    def __init__(self):
        self.root = Path(settings.MEDIA_ROOT) / "mobile-staging"

    def put(self, key: str, data: bytes):
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        return (self.root / key).read_bytes()

    def delete(self, key: str):
        path = self.root / key
        if path.exists():
            path.unlink()
