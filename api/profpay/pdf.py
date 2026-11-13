"""Remittance advices and yearly statements as deterministic PDFs (FR-PRO-007,
hashed and stored write-once as reports are, ADR-15). Black and white only:
pay documents carry no verdict colour (RUL-26)."""
from datetime import datetime, timezone as dt_tz

_REPL = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "..."}


def _latin(text) -> str:
    s = str(text if text is not None else "")
    for k, v in _REPL.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


def render(doc: dict) -> bytes:
    """doc: title, header [str], rows [(label, value)], notes [str], issued_at (datetime)."""
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_compression(True)
    pdf.set_creation_date(doc.get("issued_at") or datetime(2026, 1, 1, tzinfo=dt_tz.utc))
    pdf.set_title(_latin(doc["title"]))
    pdf.set_author("Tenmina")
    pdf.set_creator("Tenmina professional payments")
    pdf.set_producer("Tenmina")
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_page()
    w = pdf.epw

    def para(text, size=10, style="", gap=1.5):
        pdf.set_font("Helvetica", style, size)
        pdf.multi_cell(w, 5.2, _latin(text), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(gap)

    para(doc["title"], 16, "B", 2)
    for line in doc.get("header", []):
        para(line, 10, "", 0.5)
    pdf.ln(3)
    for label, value in doc.get("rows", []):
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(w * 0.6, 6, _latin(label))
        pdf.cell(w * 0.4, 6, _latin(value), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    for line in doc.get("notes", []):
        para(line, 8, "I", 0.5)
    return bytes(pdf.output())
