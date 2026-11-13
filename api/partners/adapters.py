"""PTR ports (ADR-10). Port `partner_webhooks` sends a signed outbound webhook.
`RecordingWebhookTransport` stores what would be sent and answers 200 unless the
URL contains "fail" (tests use it for back-off); `HttpWebhookTransport` posts for real."""
import hashlib
import hmac

from core.adapters import get_adapter


def sign(secret: str, timestamp: int, body: str) -> str:
    """HMAC-SHA256 over `timestamp.body` (7.3). Header: `Tenmina-Signature: t=<ts>,v1=<hex>`."""
    mac = hmac.new(secret.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={mac}"


def verify(secret: str, header: str, body: str, *, now: int, tolerance: int = 300) -> bool:
    """What a partner runs on receipt; documented for partners and used in tests."""
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        ts = int(parts["t"])
    except (KeyError, ValueError):
        return False
    if abs(now - ts) > tolerance:
        return False
    return hmac.compare_digest(sign(secret, ts, body), header)


class RecordingWebhookTransport:
    SENT: list = []

    def post(self, url: str, body: str, headers: dict) -> int:
        type(self).SENT.append({"url": url, "body": body, "headers": headers})
        return 500 if "fail" in url else 200


class HttpWebhookTransport:
    def post(self, url: str, body: str, headers: dict) -> int:  # pragma: no cover - real network
        import urllib.request

        req = urllib.request.Request(url, data=body.encode(), method="POST",
                                     headers={**headers, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status
        except Exception:  # noqa: BLE001
            return 0


def transport():
    return get_adapter("partner_webhooks", default="partners.adapters.RecordingWebhookTransport")
