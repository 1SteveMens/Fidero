"""Ports for the evidence store (ADR-10). Each has a local or fake adapter so the
whole flow runs offline:

- evidence_store: LocalWriteOnceStore stands in for S3 with Object Lock (ADR-04).
- malware_scan: FakeScanner stands in for ClamAV; it rejects the EICAR test file.
- video_preview: FakeVideoPreview makes a still placeholder instead of a compressed video.
"""
import io
import os
from datetime import date
from pathlib import Path

from django.conf import settings

EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class LocalWriteOnceStore:
    """Local stand-in for S3 with Object Lock (ADR-04): refuses to overwrite."""

    def __init__(self):
        self.root = Path(settings.MEDIA_ROOT) / "evidence"

    def put(self, key: str, data: bytes) -> str:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o440)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        return "v1"  # object version; S3 returns its version ID

    def get(self, key: str) -> bytes:
        return (self.root / key).read_bytes()

    def exists(self, key: str) -> bool:
        return (self.root / key).exists()

    def expire(self, key: str, retain_until: date, today: date) -> bool:
        """Delete an object whose lock date has passed. Object Lock refuses earlier deletes."""
        if retain_until is None or retain_until >= today:
            raise PermissionError("The object is still locked.")
        path = self.root / key
        if path.exists():
            os.chmod(path, 0o640)
            path.unlink()
        return True


class FakeScanner:
    """Stands in for ClamAV. Rejects the EICAR test string; everything else is clean."""

    name = "fake-scanner"

    def scan(self, data: bytes) -> str:
        return "rejected" if EICAR in data else "clean"


class NoopScanner(FakeScanner):
    """Name kept for settings.TENMINA["ADAPTERS"]["malware_scan"]."""


class DeferredScanner(FakeScanner):
    """An asynchronous scanner: files wait as 'pending' until record_scan() gives the verdict."""

    name = "deferred-scanner"

    def scan(self, data: bytes) -> str:
        return "rejected" if EICAR in data else "pending"


class FakeVideoPreview:
    """Makes a still placeholder (a play symbol) instead of a compressed video.
    The real adapter runs ffmpeg in the media worker (job evidence.make_previews)."""

    def make(self, data: bytes, content_type: str):
        if len(data) < 12 or data[4:8] not in (b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip"):
            raise ValueError("The video could not be read.")
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (640, 360), (32, 36, 40))
        d = ImageDraw.Draw(img)
        d.polygon([(280, 130), (280, 230), (370, 180)], fill=(200, 240, 80))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=70)
        return buf.getvalue(), "image/jpeg", 640, 360, "placeholder"
