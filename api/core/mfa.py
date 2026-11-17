"""How a person last passed an MFA step-up (ADR-13, FR-ACC-014).

A step-up is either the 6-digit authenticator code ("totp") or a signature
from an approval key held on the person's phone behind Face ID or a
fingerprint ("device_biometric"). `core.views.mfa_at(request)` returns an
`MfaAt`: the time of the step-up that also carries its method, so every
service that already passes `mfa_at=` on to `core.approvals.decide` records
the method without changing its signature.
"""
from datetime import datetime

TOTP = "totp"
DEVICE_BIOMETRIC = "device_biometric"
METHODS = (TOTP, DEVICE_BIOMETRIC)


class MfaAt(datetime):
    """A datetime that remembers the step-up method."""

    method = TOTP

    @classmethod
    def of(cls, at: datetime, method: str = TOTP) -> "MfaAt":
        out = cls(at.year, at.month, at.day, at.hour, at.minute, at.second, at.microsecond, at.tzinfo,
                  fold=at.fold)
        out.method = method if method in METHODS else TOTP
        return out

    def plain(self) -> datetime:
        return datetime(self.year, self.month, self.day, self.hour, self.minute, self.second, self.microsecond,
                        self.tzinfo, fold=self.fold)


def method_of(at, default=TOTP) -> str:
    """The step-up method behind `at`, or `default` for a plain datetime."""
    return getattr(at, "method", None) or default


def plain(at):
    """A plain datetime for storage."""
    return at.plain() if isinstance(at, MfaAt) else at
