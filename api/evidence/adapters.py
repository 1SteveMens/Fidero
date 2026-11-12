import os
from pathlib import Path

from django.conf import settings


class LocalWriteOnceStore:
    """Local stand-in for S3 with Object Lock (ADR-04): refuses to overwrite."""

    def __init__(self):
        self.root = Path(settings.MEDIA_ROOT) / "evidence"

    def put(self, key: str, data: bytes):
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o440)
        with os.fdopen(fd, "wb") as f:
            f.write(data)

    def get(self, key: str) -> bytes:
        return (self.root / key).read_bytes()

    def exists(self, key: str) -> bool:
        return (self.root / key).exists()


class NoopScanner:
    def scan(self, data: bytes) -> str:
        return "clean"
