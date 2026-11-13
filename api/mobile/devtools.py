"""A software stand-in for Tenmina Field, for seeds, tests and front-end developers.

It makes a key pair, registers through the fake attestation adapter, and builds
and signs manifests exactly as the app does (02 section 8.4). Never used in
production: real keys live in Android Keystore or the Secure Enclave.
"""
import hashlib
import io
import random
import uuid
from datetime import datetime, timezone as dt_tz

from cryptography.hazmat.primitives.asymmetric import ec, ed25519

from . import crypto

P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551


def jpeg(seed: str, *, model: str | None = None, make: str = "Samsung", when: datetime | None = None,
         size=(64, 48)) -> bytes:
    """A small JPEG with a pattern unique to `seed`, and EXIF make, model and time."""
    from PIL import Image

    rng = random.Random(seed)
    img = Image.new("RGB", size)
    bw, bh = size[0] // 8, size[1] // 6
    for bx in range(8):
        for by in range(6):
            g = rng.randint(0, 255)
            img.paste((g, (g * 7) % 256, (g * 13) % 256), (bx * bw, by * bh, (bx + 1) * bw, (by + 1) * bh))
    exif = Image.Exif()
    if model:
        exif[271], exif[272] = make, model
    if when:
        exif[306] = when.strftime("%Y:%m:%d %H:%M:%S")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85, exif=exif)
    return buf.getvalue()


def mp4(seed: str) -> bytes:
    """Bytes with an MP4 header, enough for the store's type check and the fake preview."""
    return b"\x00\x00\x00\x18ftypmp42" + hashlib.sha256(seed.encode()).digest() * 8


class FakePhone:
    def __init__(self, person, *, platform="android", key_security="tee", alg="ES256", model=None, seed=None):
        self.person, self.platform, self.key_security, self.alg = person, platform, key_security, alg
        self.model = model or ("iPhone12,8" if platform == "ios" else "SM-A045F")
        material = hashlib.sha256((seed or uuid.uuid4().hex).encode()).digest()
        if alg == "EdDSA":
            self.key = ed25519.Ed25519PrivateKey.from_private_bytes(material)
        else:
            self.key = ec.derive_private_key(int.from_bytes(material, "big") % (P256_ORDER - 1) + 1, ec.SECP256R1())
        self.device = None
        self.previous = None

    @property
    def public_key(self) -> str:
        return crypto.spki_b64(self.key.public_key())

    def attestation(self, challenge, /, **over) -> dict:
        if self.platform == "ios":
            a = {"challenge": challenge, "build": "store", "environment": "production", "counter": 0,
                 "key_id": "dev-" + self.public_key[-12:],
                 "key_sha256": hashlib.sha256(crypto.b64decode_any(self.public_key)).hexdigest()}
        else:
            a = {"challenge": challenge, "build": "store", "key_security": self.key_security,
                 "device_integrity": "MEETS_DEVICE_INTEGRITY", "app_recognized": True}
        a.update(over)
        return a

    def register(self, **attestation_overrides):
        from .services import issue_challenge, register_device

        ch = issue_challenge(self.person)
        self.device, _ = register_device(
            self.person, challenge=ch.nonce, platform=self.platform, app_id="com.tenmina.field",
            public_key=self.public_key, attestation=self.attestation(ch.nonce, **attestation_overrides),
            model=self.model, os_version="14" if self.platform == "android" else "17.5", app_version="1.0.0")
        from .models import SignedManifest

        last = SignedManifest.objects.filter(device=self.device).order_by("-received_at").first()
        self.previous = last.item_sha256 if last else None
        return self.device

    def sign(self, manifest: dict) -> dict:
        return {"manifest": manifest, "signature": crypto.sign(self.key, crypto.canonical(manifest)),
                "signature_alg": self.alg}

    def _base(self, subject_type, subject_id, *, lat, lng, accuracy, captured_at, offset_ms, mock, client_item_id,
              chain, emulator=False):
        when = captured_at or datetime.now(dt_tz.utc)
        m = {
            "client_item_id": client_item_id or str(uuid.uuid4()),
            "device_id": str(self.device.pk),
            "subject": {"type": subject_type, "id": str(subject_id)},
            "captured_at_device": when.isoformat().replace("+00:00", "Z"),
            "elapsed_realtime_ms": 88123456,
            "last_server_time_sync": {"server": when.isoformat().replace("+00:00", "Z"), "offset_ms": offset_ms},
            "camera": {"lens": "back", "model": self.model, "platform": self.platform, "app_version": "1.0.0"},
        }
        if emulator:
            m["camera"]["emulator"] = True
        if lat is not None:
            m["location"] = {"lat": lat, "lng": lng, "accuracy_m": accuracy, "provider": "gps", "mock": mock}
        if chain and self.previous:
            m["previous_item_sha256"] = self.previous
        return m

    def capture(self, subject_type, subject_id, data: bytes, *, requirement_key="", media_type="image/jpeg",
                lat=5.6037, lng=-0.187, accuracy=5.0, captured_at=None, offset_ms=0, mock=False, client_item_id=None,
                chain=True, emulator=False) -> dict:
        m = self._base(subject_type, subject_id, lat=lat, lng=lng, accuracy=accuracy, captured_at=captured_at,
                       offset_ms=offset_ms, mock=mock, client_item_id=client_item_id, chain=chain, emulator=emulator)
        m["schema"] = "tenmina.evidence.v1"
        if requirement_key:
            m["subject"]["requirement_key"] = requirement_key
        sha = hashlib.sha256(data).hexdigest()
        m["media"] = {"type": media_type, "size_bytes": len(data), "sha256": sha}
        if chain:
            self.previous = sha
        return self.sign(m)

    def check(self, kind, subject_type, subject_id, *, lat=5.6037, lng=-0.187, accuracy=8.0, captured_at=None,
              offset_ms=0, mock=False, client_item_id=None, chain=True) -> dict:
        m = self._base(subject_type, subject_id, lat=lat, lng=lng, accuracy=accuracy, captured_at=captured_at,
                       offset_ms=offset_ms, mock=mock, client_item_id=client_item_id, chain=chain)
        m["schema"], m["kind"] = "tenmina.checkin.v1", kind
        if chain:
            self.previous = crypto.sha256_hex(crypto.canonical(m))
        return self.sign(m)
