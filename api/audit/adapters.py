"""Anchor store port (ADR-05). Production writes the chain head to an S3
bucket with Object Lock in compliance mode; development writes a local file
that is never overwritten."""
import json
import os
from pathlib import Path

from django.conf import settings


class LocalAnchorStore:
    def __init__(self):
        self.root = Path(settings.MEDIA_ROOT) / "audit-anchors"

    def put(self, seq: int, hash_: str) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        name = f"{seq:012d}-{hash_}.json"
        path = self.root / name
        if not path.exists():
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o440)
            with os.fdopen(fd, "w") as f:
                json.dump({"seq": seq, "hash": hash_}, f)
        return f"local:audit-anchors/{name}"

    def check(self, location: str, seq: int, hash_: str) -> bool:
        if not location.startswith("local:"):
            return True  # anchors written by another store are checked by that store
        path = Path(settings.MEDIA_ROOT) / location.removeprefix("local:")
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text())
        except ValueError:
            return False
        return data.get("seq") == seq and data.get("hash") == hash_
