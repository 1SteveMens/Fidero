"""The family statement PDF (US-FEE-007 AC2). Built-in fonts only; the stored bytes and their hash are what
count, never a re-render."""
from datetime import datetime, timezone as dt_tz


def _latin(text) -> str:
    from reports.pdf import latin

    return latin(text)


def render_statement(data: dict, *, client_name: str) -> bytes:
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_compression(True)
    pdf.set_creation_date(datetime.now(dt_tz.utc).replace(microsecond=0))
    fm = data["family_member"]
    pdf.set_title(_latin(f"Statement for {fm['full_name']}"))
    pdf.set_author("Tenmina")
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, _latin(f"Statement for {fm['full_name']} ({fm['relationship']})"), new_x="LMARGIN",
             new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _latin(f"Prepared for {client_name} on {datetime.now(dt_tz.utc):%d %B %Y}"), new_x="LMARGIN",
             new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "Bills, payments and receipts", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    for line in data["lines"]:
        amt = line.get("amount")
        money = f"{amt['currency']} {float(amt['amount']):,.2f}" if amt else ""
        text = (f"{line['at'][:10]}  {line['type'].upper():8}  {line['institution']}  {line['reference']}  "
                f"{line.get('description') or ''}  {money}  [{line['status']}]")
        pdf.multi_cell(0, 5, _latin(text), new_x="LMARGIN", new_y="NEXT")
    if not data["lines"]:
        pdf.cell(0, 6, "No bills yet.", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "Totals", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    for t in data["totals"]:
        pdf.cell(0, 5, _latin(f"{t['currency']}: billed {t['invoiced']}, paid {t['paid']}, awaiting payment "
                              f"{t['awaiting_payment']}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "Held at the bank", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    for h in data["held_at_bank"]:
        pdf.cell(0, 5, _latin(f"{h['escrow_reference']}: held {h['held_at_bank']['currency']} "
                              f"{h['held_at_bank']['amount']}, awaiting the bank {h['awaiting_bank']['amount']}, "
                              f"available {h['available_to_instruct']['amount']}"), new_x="LMARGIN", new_y="NEXT")
    if not data["held_at_bank"]:
        pdf.cell(0, 5, "Nothing is held at the bank.", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 8)
    pdf.multi_cell(0, 4, _latin(data["note"]), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
