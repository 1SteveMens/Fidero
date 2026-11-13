"""PMG ports and adapters (ADR-10, 02 section 9.3).

Port `pmg_rent_statement`: the bank's statement lines for the owner's rent
account, shared under the owner's written mandate (FR-PMG-003). Adapters:

- `CsvRentStatement` (default): the `file` route (the bank sends the owner's
  account statement by SFTP) and the `manual` route (the owner uploads the
  bank's statement for that account). Both are CSV with one row per line.
- an `api` adapter where the bank offers third-party read access [TO VERIFY]
  would return the same rows.

Whether the bank will share a customer's statement under a mandate is open
(TQ-17). The format below is a working assumption [TO VERIFY] with the bank.
"""
import csv
import io
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from core.adapters import get_adapter


def rent_statement():
    return get_adapter("pmg_rent_statement", default="propertymgmt.adapters.CsvRentStatement")


def normalise_account(number: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", number or "").upper()


class CsvRentStatement:
    """One row per statement line:

        account_number,booked_on,kind,amount,currency,bank_reference,counterparty_name,narrative

    `account_number` is the account the line belongs to. kind is credit or debit.
    """

    REQUIRED = ("account_number", "booked_on", "kind", "amount", "currency")

    def parse(self, data: bytes) -> list[dict]:
        text = data.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        missing = [c for c in self.REQUIRED if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"The file is missing the columns: {', '.join(missing)}.")
        rows = []
        for i, r in enumerate(reader, start=1):
            kind = (r.get("kind") or "").strip().lower()
            if kind not in ("credit", "debit"):
                raise ValueError(f"Line {i}: kind must be credit or debit.")
            try:
                amount = Decimal((r.get("amount") or "").strip()).quantize(Decimal("0.01"))
                booked = date.fromisoformat((r.get("booked_on") or "").strip())
            except (InvalidOperation, ValueError) as exc:
                raise ValueError(f"Line {i}: the amount or the date cannot be read.") from exc
            if amount <= 0:
                raise ValueError(f"Line {i}: the amount must be more than zero.")
            rows.append({
                "line_no": i,
                "account_number": normalise_account(r.get("account_number")),
                "booked_on": booked,
                "kind": kind,
                "amount": amount,
                "currency": (r.get("currency") or "").strip().upper(),
                "bank_reference": (r.get("bank_reference") or "").strip(),
                "counterparty_name": (r.get("counterparty_name") or "").strip(),
                "narrative": (r.get("narrative") or "").strip(),
            })
        return rows


def to_escrow_csv(rows: list[dict], statement_ref: str) -> bytes:
    """The accepted lines in the escrow statement format, tagged with the
    mandate's statement reference so ESC stores them as `owner_rent` lines."""
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["booked_on", "kind", "amount", "currency", "virtual_account_ref", "bank_reference",
                "counterparty_bank", "counterparty_account", "counterparty_name", "narrative"])
    for r in rows:
        w.writerow([r["booked_on"].isoformat(), r["kind"], f"{r['amount']:.2f}", r["currency"], statement_ref,
                    r["bank_reference"], "", "", r["counterparty_name"], r["narrative"]])
    return out.getvalue().encode()
