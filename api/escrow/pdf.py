"""The bank release instruction as a PDF for people (02 section 9.1, FR-ESC-008, IF-01).

The PDF is rendered from the signed structured file, never from the database,
so both say the same thing. It is deterministic: the same instruction always
gives the same bytes (fixed creation date, no random file identifier), so its
SHA-256 can be checked again at any time. Built-in fonts only.
"""
import json
from datetime import datetime, timezone as dt_tz

FIXED_DATE = datetime(2026, 1, 1, tzinfo=dt_tz.utc)

LABELS = {
    "release": "Release instruction", "partial_release": "Partial release instruction",
    "cancel_refund": "Refund instruction", "conversion": "Conversion instruction",
}


def _latin(text) -> str:
    from reports.pdf import latin

    return latin(str(text if text is not None else ""))


def _at(value) -> datetime:
    try:
        d = datetime.fromisoformat(str(value))
        return d if d.tzinfo else d.replace(tzinfo=dt_tz.utc)
    except (TypeError, ValueError):
        return FIXED_DATE


def render(doc_bytes: bytes, *, document_sha256: str) -> bytes:
    """`doc_bytes` is the signed JSON instruction; `document_sha256` its hash, printed on every page."""
    from fpdf import FPDF

    doc = json.loads(doc_bytes)
    approvals = doc.get("approvals") or []
    created = _at(approvals[-1]["at"]) if approvals else FIXED_DATE

    pdf = FPDF(format="A4")
    pdf.set_compression(True)
    pdf.set_creation_date(created.replace(microsecond=0))
    title = f"{LABELS.get(doc.get('kind'), 'Instruction')} {doc.get('escrow_reference', '')}"
    pdf.set_title(_latin(title))
    pdf.set_author("Tenmina")
    pdf.set_creator("Tenmina escrow service")
    pdf.set_producer("Tenmina")
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_page()
    w = pdf.epw

    def line(text, size=10, style="", gap=0.8):
        pdf.set_font("Helvetica", style, size)
        pdf.multi_cell(w, 5.2, _latin(text), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(gap)

    def head(text):
        pdf.ln(1.5)
        line(text, 11, "B", 0.5)

    line(title, 16, "B", 2)
    line(f"Instruction ID: {doc.get('instruction_id', '')}")
    line(f"Escrow reference: {doc.get('escrow_reference', '')}    Bank reference: {doc.get('bank_reference') or '-'}")
    line(f"Format: {doc.get('format', '')}", 8, "I")

    head("Pay from")
    pa = doc.get("programme_account") or {}
    line(f"Programme escrow account: {pa.get('name', '')}, ending {pa.get('number_last4', '')}")
    line(f"Virtual account: {doc.get('pay_from_virtual_account') or '-'}. Pay only from this escrow's money in it "
         "(RUL-34).")

    head("Amount")
    line(f"{doc.get('currency', '')} {doc.get('amount', '')}", 13, "B")
    if doc.get("holdback") not in (None, "0.00"):
        line(f"Holdback: {doc.get('currency', '')} {doc['holdback']}")
    line(f"Value date: {doc.get('value_date', '')}")
    if doc.get("held_back_share"):
        hb = doc["held_back_share"]
        line(f"Left in escrow: {doc.get('currency', '')} {hb.get('amount', '')}. Released only when: "
             f"{hb.get('condition') or '-'}")

    if doc.get("payee"):
        p = doc["payee"]
        head("Pay to (from the bank's own record of the account)")
        line(f"Account name: {p.get('name', '')}")
        line(f"Bank: {p.get('bank', '')}    Account number: {p.get('account_number', '')}")
        line(f"Payee kind: {p.get('kind', '')}    Account version: {p.get('account_version', '')}")
        line("By bank transfer to this account only. There is no cash instruction.", 9, "I")
    if doc.get("refund_to"):
        r = doc["refund_to"]
        head("Refund to")
        line(f"Basis: {r.get('basis', '')}")
        line(f"Account name: {r.get('name', '')}    Bank: {r.get('bank', '')}    "
             f"Account number: {r.get('account_number', '')}")
        dep = doc.get("refunds_deposit") or {}
        line(f"Returns the deposit {dep.get('bank_reference', '')} of {dep.get('date', '')}.")
    if doc.get("conversion"):
        c = doc["conversion"]
        head("Conversion")
        line(f"Convert to {c.get('to_currency', '')} at the client's accepted quote {c.get('quote_id', '')}: rate "
             f"{c.get('offered_rate', '')}, margin {c.get('margin_pct', '')}%, expected "
             f"{c.get('to_currency', '')} {c.get('expected_to_amount', '')}.")
        line(f"Programme rate reference: {c.get('programme_rate_id') or '-'}. {c.get('report', '')}")

    subj = doc.get("subject") or {}
    if subj.get("type"):
        head("What it pays for")
        line(f"{subj.get('type', '').replace('_', ' ')}: {subj.get('label') or subj.get('id', '')}")

    head("Conditions closed with evidence")
    conds = doc.get("conditions_closed") or []
    for c in conds:
        line(f"- {c.get('text', '')} (closed {str(c.get('closed_at') or '')[:10]})")
    if not conds:
        line("None for this instruction.")

    head("Approvals")
    line(f"Client approved: {doc.get('client_approved_at') or '-'}")
    for a in approvals:
        line(f"Approval {a.get('slot', '')}: {a.get('approver', '')} at {a.get('at', '')}")

    pdf.ln(3)
    line(f"Signed structured file SHA-256: {document_sha256}", 8, "I", 0.3)
    line("The structured file is the instruction; this PDF shows the same content for people. The signature on "
         "the structured file is checked with Tenmina's public key held by the bank.", 8, "I", 0.3)
    return bytes(pdf.output())
