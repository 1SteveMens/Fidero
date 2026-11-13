"""ESC ports and adapters (ADR-10). Each port has a fake or manual adapter so
the whole escrow workflow runs before any bank or rate integration exists.

Ports (settings.TENMINA["ADAPTERS"] or the defaults below):
- bank_instructions: send a signed instruction to the bank (IF-01, 9.1).
- bank_statement: parse the bank's statement file (FR-ESC-011).
- bank_name_check: the bank's own account-name lookup (9.2, FR-ESC-015).
- instruction_signer: sign an instruction hash (stands in for KMS, 9.1).
- fx_rates: reference rates and providers' published rates (IF-14, IF-15).
"""
import csv
import hashlib
import hmac
import io
from datetime import date, datetime
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from core.adapters import get_adapter


def bank_instructions():
    return get_adapter("bank_instructions", default="escrow.adapters.ManualBankInstructions")


def bank_statement():
    return get_adapter("bank_statement", default="escrow.adapters.CsvStatementParser")


def bank_name_check():
    return get_adapter("bank_name_check", default="escrow.adapters.FakeBankNameCheck")


def signer():
    return get_adapter("instruction_signer", default="escrow.adapters.FakeKmsSigner")


def rate_source():
    return get_adapter("fx_rates", default="escrow.adapters.FakeRateSource")


# --------------------------------------------------------------------------- bank instructions

class SendFailed(Exception):
    pass


class ManualBankInstructions:
    """The R1 path: Tenmina produces the signed instruction document and sends
    it by the agreed secure email `[TO VERIFY]`; staff record the bank's
    confirmation with proof, checked by a second person (FR-ESC-004)."""

    channel = "secure_email_manual"

    def send(self, *, instruction, document: bytes, signature: str, recipient: str) -> dict:
        if not recipient:
            raise SendFailed("The bank partner has no contact address for instructions.")
        ref = "MAN-" + hashlib.sha256(document).hexdigest()[:12].upper()
        return {"channel": self.channel, "recipient": recipient, "reference": ref, "sent_at": timezone.now()}

    def open_virtual_account(self, *, escrow, programme_account, currency) -> str | None:
        """The bank issues virtual account numbers; staff record them by hand."""
        return None


class DownBankInstructions(ManualBankInstructions):
    """Tests and drills: the channel is down (TC-ESC-008-03, TC-ESC-018-03)."""

    def send(self, **kw):
        raise SendFailed("The bank channel did not answer.")


class FakeBankApi(ManualBankInstructions):
    """A bank API that issues virtual accounts at once (demo, US-ESC-012)."""

    channel = "bank_api"

    def open_virtual_account(self, *, escrow, programme_account, currency) -> str | None:
        return f"VA-{programme_account.country.code}-{currency}-{escrow.reference.split('-')[-1]}"


# --------------------------------------------------------------------------- statement files

class CsvStatementParser:
    """The agreed statement format `[TO VERIFY]` with the bank. One row per line:

    booked_on,kind,amount,currency,virtual_account_ref,bank_reference,counterparty_bank,
    counterparty_account,counterparty_name,narrative

    kind is credit, debit or position (the bank's own figure for a virtual account).
    """

    REQUIRED = ("booked_on", "kind", "amount", "currency")

    def parse(self, data: bytes) -> list[dict]:
        text = data.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        missing = [c for c in self.REQUIRED if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"The file is missing the columns: {', '.join(missing)}.")
        rows = []
        for i, r in enumerate(reader, start=1):
            kind = (r.get("kind") or "").strip().lower()
            if kind not in ("credit", "debit", "position"):
                raise ValueError(f"Line {i}: kind must be credit, debit or position.")
            rows.append({
                "line_no": i,
                "booked_on": date.fromisoformat(r["booked_on"].strip()),
                "kind": kind,
                "amount": Decimal(r["amount"].strip()).quantize(Decimal("0.01")),
                "currency": r["currency"].strip().upper(),
                "virtual_account_ref": (r.get("virtual_account_ref") or "").strip(),
                "bank_reference": (r.get("bank_reference") or "").strip(),
                "counterparty_bank": (r.get("counterparty_bank") or "").strip(),
                "counterparty_account": (r.get("counterparty_account") or "").strip(),
                "counterparty_name": (r.get("counterparty_name") or "").strip(),
                "narrative": (r.get("narrative") or "").strip(),
            })
        return rows


# --------------------------------------------------------------------------- name check (9.2)

class FakeBankNameCheck:
    """The bank's account-name lookup `[TO VERIFY]` (TQ-14). The fake returns
    the name a test registered for the number; numbers starting 999 belong to
    someone else ("UNKNOWN HOLDER"); numbers ending 0000 are not covered, so
    a bank letter is needed instead."""

    REGISTRY: dict = {}
    available = True

    def lookup(self, *, bank_name: str, account_number: str, claimed_name: str = "") -> dict:
        number = "".join(ch for ch in account_number if ch.isalnum())
        if not type(self).available or number.endswith("0000"):
            return {"status": "not_covered"}
        name = self.REGISTRY.get(number)
        if name is None:
            name = "UNKNOWN HOLDER" if number.startswith("999") else claimed_name
        raw = f"{bank_name}|{number}|{name}|{timezone.now().isoformat()}".encode()
        return {"status": "found", "name": name, "raw_sha256": hashlib.sha256(raw).hexdigest()}


# --------------------------------------------------------------------------- signing (9.1)

class FakeKmsSigner:
    """Stands in for the KMS asymmetric key (ECC P-256) held by the dispatch
    role. Development signs with an HMAC of the secret key."""

    key_id = "dev-hmac-sha256"

    def _key(self):
        return (settings.SECRET_KEY + ":esc-instruction").encode()

    def sign(self, digest_hex: str) -> str:
        return hmac.new(self._key(), digest_hex.encode(), hashlib.sha256).hexdigest()

    def verify(self, digest_hex: str, signature: str) -> bool:
        return hmac.compare_digest(self.sign(digest_hex), signature or "")


# --------------------------------------------------------------------------- rates (IF-14, IF-15)

class FakeRateSource:
    """Synthetic reference rates and provider quotes. Every figure is a test
    fixture, not market data. A provider's own margin and fee come from its
    adm_partner details (`margin_pct`, `fee`); `fails` lists providers whose
    collection fails today."""

    RATES = {("USD", "GHS"): Decimal("15.00"), ("GBP", "GHS"): Decimal("19.00"), ("EUR", "GHS"): Decimal("16.20"),
             ("USD", "NGN"): Decimal("1550.00"), ("GBP", "NGN"): Decimal("1960.00")}
    fails: set = set()
    stale_reference = False

    def reference_rate(self, *, source, from_currency: str, to_currency: str) -> dict:
        rate = self.RATES.get((from_currency, to_currency))
        if rate is None:
            inverse = self.RATES.get((to_currency, from_currency))
            if inverse is None:
                raise LookupError(f"No reference rate for {from_currency}/{to_currency}.")
            rate = (Decimal(1) / inverse).quantize(Decimal("0.00000001"))
        published = timezone.now()
        if type(self).stale_reference:
            published = published - timezone.timedelta(days=2)
        raw = f"{source.pk}|{from_currency}|{to_currency}|{rate}|{published.isoformat()}".encode()
        return {"rate": rate, "published_at": published, "raw_sha256": hashlib.sha256(raw).hexdigest()}

    def provider_quote(self, *, provider, from_currency: str, to_currency: str, send_amount: Decimal,
                       reference_rate: Decimal) -> dict:
        if str(provider.pk) in type(self).fails or provider.name in type(self).fails:
            raise ConnectionError(f"{provider.name} did not answer.")
        d = provider.details or {}
        margin = Decimal(str(d.get("margin_pct", "1.0")))
        fee = Decimal(str(d.get("fee", "5.00")))
        rate = (reference_rate * (Decimal(100) - margin) / Decimal(100)).quantize(Decimal("0.00000001"))
        delivered = ((send_amount - fee) * rate).quantize(Decimal("0.01"))
        raw = f"{provider.pk}|{rate}|{fee}|{delivered}|{datetime.now().isoformat()}".encode()
        return {"rate": rate, "fees_total": fee, "delivered_amount": delivered, "published_at": timezone.now(),
                "raw_sha256": hashlib.sha256(raw).hexdigest()}
