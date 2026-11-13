"""PRO ports and adapters (ADR-10, ADR-23 point 4).

Port `pro_bulk_file`: builds the bulk payment file for Tenmina's operating bank
or mobile money provider and reads its confirmation file. R1 builds one
format (EN-78, TQ-27). The real column layout is the bank's `[TO VERIFY]`;
`GenericCsvBulkFile` is a plain CSV a staff member uploads in the bank's own
portal, and the confirmation CSV is read back with the same columns. No bank
API is called.
"""
import csv
import io
from decimal import Decimal, InvalidOperation

from core.adapters import get_adapter


class GenericCsvBulkFile:
    """Bulk credit CSV [TO VERIFY against the operating bank's format, Q-26, EN-78]."""

    name = "generic_csv_v1"
    content_type = "text/csv"
    extension = "csv"
    HEADER = ["record_type", "debit_bank", "debit_account", "debit_account_name", "credit_bank", "credit_account",
              "credit_account_name", "amount", "currency", "payment_reference", "narrative"]

    def build(self, run: dict) -> bytes:
        """`run` is a plain dict: reference, currency, total_net, debit {bank, account, name} and lines
        [{reference, bank, account, account_name, net, narrative}]. Deterministic: same run, same bytes."""
        out = io.StringIO()
        w = csv.writer(out, lineterminator="\n")
        w.writerow(self.HEADER)
        d = run["debit"]
        for ln in run["lines"]:
            w.writerow(["CR", d["bank"], d["account"], d["name"], ln["bank"], ln["account"], ln["account_name"],
                        f"{Decimal(ln['net']):.2f}", run["currency"], ln["reference"], ln["narrative"]])
        w.writerow(["TOTAL", d["bank"], d["account"], d["name"], "", "", "", f"{Decimal(run['total_net']):.2f}",
                    run["currency"], run["reference"], f"{len(run['lines'])} lines"])
        return out.getvalue().encode()

    def parse_confirmation(self, data: bytes) -> list[dict]:
        """Rows of the bank's confirmation: payment_reference, status (paid, failed), bank_reference, reason,
        amount. Unknown statuses are returned as given; the service treats them as unconfirmed."""
        text = data.decode("utf-8-sig")
        rows = []
        for r in csv.DictReader(io.StringIO(text)):
            ref = (r.get("payment_reference") or r.get("reference") or "").strip()
            if not ref:
                continue
            amount = None
            try:
                amount = Decimal(str(r.get("amount") or "").strip()) if r.get("amount") else None
            except InvalidOperation:
                amount = None
            rows.append({"reference": ref, "status": (r.get("status") or "").strip().lower(),
                         "bank_reference": (r.get("bank_reference") or "").strip(),
                         "reason": (r.get("reason") or r.get("failure_reason") or "").strip(), "amount": amount})
        return rows


FORMATS = {GenericCsvBulkFile.name: GenericCsvBulkFile}


def bulk_file(file_format: str | None = None):
    if file_format and file_format in FORMATS:
        return FORMATS[file_format]()
    return get_adapter("pro_bulk_file", default="profpay.adapters.GenericCsvBulkFile")
