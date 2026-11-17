"""How a person last passed an MFA step-up (ADR-13, FR-ACC-014).

A step-up is the 6-digit authenticator code ("totp"), a signature from an
approval key held on the person's phone behind Face ID or a fingerprint
("device_biometric"), or, for clients only, a 6-digit code sent by SMS to the
confirmed phone ("sms_code", decision of 17 November 2026). Staff and anyone
holding release or payment rights never step up by SMS. `core.views.mfa_at(request)` returns an
`MfaAt`: the time of the step-up that also carries its method, so every
service that already passes `mfa_at=` on to `core.approvals.decide` records
the method without changing its signature.
"""
from datetime import datetime

TOTP = "totp"
DEVICE_BIOMETRIC = "device_biometric"
SMS_CODE = "sms_code"
METHODS = (TOTP, DEVICE_BIOMETRIC, SMS_CODE)
# Never step up or approve with an SMS code (also enforced in PostgreSQL).
NO_SMS_ROLES = ("CM", "RV", "AD", "AN", "DPO", "SUP", "RR", "PY")


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


def client_method(at) -> str:
    """How a client's approval is recorded when it rests on a step-up:
    "device_biometric", "sms_code", or "mfa_step_up" for the authenticator."""
    m = method_of(at)
    return m if m in (DEVICE_BIOMETRIC, SMS_CODE) else "mfa_step_up"
