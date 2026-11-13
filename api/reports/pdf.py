"""Deterministic report PDFs (ADR-15, FR-RPT-007).

The same report renders to the same bytes: built-in fonts, no images fetched at
render time, the creation date fixed to the release time and no random file
identifier. Only the stored bytes count for verification; a re-render is never
used to check a hash. The hash is never printed inside the PDF (it would be
circular); it is shown on the public check page.

The renderer is a port (`report_pdf`) so a WeasyPrint worker can replace it.
"""
import re
from datetime import datetime, timezone as dt_tz

from core.adapters import get_adapter

_REPL = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-",
         "…": "...", " ": " ", "•": "-"}


def latin(text) -> str:
    s = str(text if text is not None else "")
    for k, v in _REPL.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


def findings_text(findings) -> list[str]:
    if not findings:
        return []
    if isinstance(findings, str):
        return [findings]
    out = []
    if findings.get("text"):
        out.append(str(findings["text"]))
    for k, v in findings.items():
        if k in ("text", "version", "satellite"):
            continue
        if isinstance(v, (list, tuple)):
            v = "; ".join(str(x) for x in v)
        elif isinstance(v, dict):
            v = "; ".join(f"{a}: {b}" for a, b in v.items())
        out.append(f"{k.replace('_', ' ').capitalize()}: {v}")
    sat = findings.get("satellite")
    if isinstance(sat, dict) and sat.get("section_4_text"):
        out.append(str(sat["section_4_text"]))
    return out


class Fpdf2Renderer:
    name = "fpdf2"

    def render(self, doc: dict) -> bytes:
        from fpdf import FPDF

        pdf = FPDF(format="A4")
        pdf.set_compression(True)
        fixed = doc.get("rendered_at") or datetime(2026, 1, 1, tzinfo=dt_tz.utc)
        pdf.set_creation_date(fixed)
        pdf.set_title(latin(doc["title"]))
        pdf.set_author("Tenmina")
        pdf.set_creator("Tenmina report service")
        pdf.set_producer("Tenmina")
        pdf.set_auto_page_break(True, margin=18)
        pdf.add_page()
        w = pdf.epw

        def para(text, size=10, style="", gap=1.5):
            pdf.set_font("Helvetica", style, size)
            pdf.multi_cell(w, 5.2, latin(text), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(gap)

        para(doc["title"], 16, "B", 2)
        for line in doc.get("header", []):
            para(line, 10)
        if doc.get("verdict"):
            para(f"Overall verdict: {doc['verdict'].upper()}", 14, "B", 3)
        for s in doc["sections"]:
            para(f"{s['label']}. {s['title']}", 12, "B", 0.5)
            if s.get("verdict"):
                para(f"Section verdict: {s['verdict']}", 10, "I", 0.5)
            for line in s.get("lines", []):
                para(line, 10, "", 0.8)
            pdf.ln(2)
        for line in doc.get("footer", []):
            para(line, 8, "I", 0.5)
        return bytes(pdf.output())


def renderer():
    return get_adapter("report_pdf", default="reports.pdf.Fpdf2Renderer")


EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"\+?\d[\d\s-]{7,}\d")
COORD = re.compile(r"-?\d{1,3}\.\d{3,}")
DIGITAL_ADDRESS = re.compile(r"\b[A-Z]{2}-\d{3,4}-\d{3,5}\b")


def redact(text: str, names: list[str]) -> str:
    """FR-RPT-011: names, plot numbers, coordinates and contacts removed."""
    s = str(text)
    for n in sorted({n for n in names if n and len(n.strip()) >= 2}, key=len, reverse=True):
        s = re.sub(re.escape(n.strip()), "[removed]", s, flags=re.IGNORECASE)
    s = EMAIL.sub("[email removed]", s)
    s = DIGITAL_ADDRESS.sub("[address removed]", s)
    s = COORD.sub("[coordinate removed]", s)
    s = PHONE.sub("[phone removed]", s)
    return s
