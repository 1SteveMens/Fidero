"""Scheduled escrow jobs and the PDF instruction: RUL-22, RUL-28, RUL-34, FR-ESC-008, FR-ESC-016, FR-ESC-019
(02 sections 7.12 and 9.1)."""
import hashlib
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from audit.models import AuditEvent
from escrow import adapters, services
from escrow.models import BankPosition, Escrow, Payee, PayeeChange, ReleaseInstruction
from notifications.models import Message


class PositionsBank(adapters.ManualBankInstructions):
    """A bank channel that reports its daily figure per virtual account (tests only)."""

    REPORT: dict = {}

    def daily_positions(self, *, country, as_of):
        return dict(self.REPORT)


@pytest.fixture
def positions_bank(settings):
    settings.TENMINA = {**settings.TENMINA, "ADAPTERS": {**settings.TENMINA["ADAPTERS"],
                                                          "bank_instructions": "escrow.tests.test_jobs.PositionsBank"}}
    PositionsBank.REPORT = {}
    yield PositionsBank
    PositionsBank.REPORT = {}


# ----------------------------------------------------------------- escrow.payee_expiry (RUL-22)

def test_payee_expiry_sends_payee_back_to_pending(b):
    """RUL-22, 7.12 escrow.payee_expiry: past valid_until the payee goes to pending, its live instruction and the
    instruction's open approval are withdrawn, staff are told, and a second run changes nothing."""
    hf = b.held_funds(None)
    ins = b.fee_release(hf, "100.00")
    school = b.payee("school")
    assert school.verification_status == "verified"
    Payee.objects.filter(pk=school.pk).update(valid_until=timezone.localdate() - timedelta(days=1))
    fresh = b.payee("seller")
    Payee.objects.filter(pk=fresh.pk).update(valid_until=timezone.localdate() + timedelta(days=30))

    out = services.expire_payees()
    school.refresh_from_db()
    ins.refresh_from_db()
    assert out["expired"] >= 1 and school.verification_status == "pending"
    assert school.verified_by_id is None and school.approval_request_id is None
    assert ins.status == "withdrawn" and ins.approval_request.status != "open"
    assert Payee.objects.get(pk=fresh.pk).verification_status == "verified"
    assert Message.objects.filter(template="payee_reverification_due", person=b.rv).exists()
    assert AuditEvent.objects.filter(action="payee.verification_expired", entity_id=str(school.pk)).exists()
    assert services.expire_payees()["expired"] == 0


# ----------------------------------------------------------------- escrow.cooling_off_end (RUL-28)

def _applied_change(b, number):
    from escrow.tests.test_payees import _change

    e = b.ready_purchase()
    seller = b.payee("seller")
    adapters.FakeBankNameCheck.REGISTRY[number] = "Ato Estates Ltd"
    try:
        ch = _change(b, e, seller, number=number)
    finally:
        adapters.FakeBankNameCheck.REGISTRY.pop(number, None)
    services.client_approve_change(ch, b.client, mfa_at=timezone.now())
    ch.refresh_from_db()
    services.decide_change(ch, b.rv, decision="approve", mfa_at=timezone.now())
    services.decide_change(ch, b.rv2, decision="approve", mfa_at=timezone.now())
    ch.refresh_from_db()
    assert ch.status == "applied"
    return e, seller, ch


def _end_now(ch, seller):
    past = timezone.now() - timedelta(seconds=5)
    PayeeChange.objects.filter(pk=ch.pk).update(applied_at=past - timedelta(hours=72), cooling_off_until=past)
    Payee.objects.filter(pk=seller.pk).update(cooling_off_until=past)


def test_cooling_off_end_tells_client_and_case_manager(b):
    """FR-ESC-016, RUL-28, 7.12 escrow.cooling_off_end: once the cooling-off has ended the change is marked, the
    client and the case manager are told, and a second run does nothing."""
    e, seller, ch = _applied_change(b, "4400112233461")
    assert services.end_cooling_off()["ended"] == 0  # still cooling off: untouched
    assert PayeeChange.objects.get(pk=ch.pk).cooling_off_ended_at is None

    _end_now(ch, seller)
    out = services.end_cooling_off()
    ch.refresh_from_db()
    assert out["ended"] == 1 and ch.cooling_off_ended_at is not None and ch.status == "applied"
    assert Message.objects.filter(template="payee_change_effective", person=b.client, subject_id=str(ch.pk)).exists()
    assert Message.objects.filter(template="payee_change_effective", person=b.cm, subject_id=str(ch.pk)).exists()
    assert AuditEvent.objects.filter(action="payee_change.cooling_off_ended", entity_id=str(ch.pk)).exists()
    assert services.end_cooling_off()["ended"] == 0


def test_cooling_off_end_approves_nothing(b):
    """RUL-28, silence is never approval: after the cooling-off a release still waits for the client and two
    staff."""
    e, seller, ch = _applied_change(b, "4400112233462")
    _end_now(ch, seller)
    before = ReleaseInstruction.objects.filter(escrow=e).count()
    services.end_cooling_off()
    assert ReleaseInstruction.objects.filter(escrow=e).count() == before
    ins = services.request_release(Escrow.objects.get(pk=e.pk), requested_by=b.cm)
    assert ins.status == "awaiting_client" and ins.payee_account_version == 2


# ----------------------------------------------------------------- escrow.reconcile_positions (FR-ESC-019)

def test_reconcile_records_bank_figure_and_matches(b, positions_bank):
    """FR-ESC-019, RUL-34: the bank's figure for the day is recorded and compared with the confirmed events."""
    e = b.ready_purchase("2500.00")
    day = timezone.localdate() - timedelta(days=1)
    positions_bank.REPORT = {(e.virtual_account_ref, e.currency): Decimal("2500.00")}
    out = services.reconcile_positions(as_of=day)
    pos = BankPosition.objects.get(escrow=e, as_of=day)
    assert pos.source == "api" and pos.status == "matched" and out["matched"] >= 1
    assert e.reference + f" ({e.currency})" not in out["missing"].get("GH", [])
    again = services.reconcile_positions(as_of=day)
    assert BankPosition.objects.filter(escrow=e, as_of=day).count() == 1 and again["recorded"] == 0


def test_reconcile_mismatch_blocks_release(b, positions_bank, codes):
    """FR-ESC-019, RUL-34: a bank figure that differs from the confirmed events blocks releases and goes to a
    reviewer."""
    e = b.ready_purchase("2500.00")
    day = timezone.localdate() - timedelta(days=1)
    positions_bank.REPORT = {(e.virtual_account_ref, e.currency): Decimal("2400.00")}
    out = services.reconcile_positions(as_of=day)
    assert BankPosition.objects.get(escrow=e, as_of=day).status == "mismatch" and out["mismatch"] >= 1
    assert Message.objects.filter(template="bank_position_mismatch", person=b.rv).exists()
    with pytest.raises(Exception) as ei:
        services.request_release(Escrow.objects.get(pk=e.pk), requested_by=b.cm)
    assert "bank-position-mismatch" in codes(ei.value)


def test_reconcile_lists_missing_figures_for_case_manager(b, positions_bank):
    """7.12: an escrow with no bank figure for the day is listed for the case manager; a figure already on the
    statement is left as it was."""
    e = b.ready_purchase("2500.00")
    other = b.ready_purchase("1500.00")
    day = timezone.localdate() - timedelta(days=2)
    services.record_bank_position(other, as_of=day, reported_held_amount="1500.00", source="statement")
    out = services.reconcile_positions(as_of=day)
    missing = out["missing"]["GH"]
    assert f"{e.reference} ({e.currency})" in missing
    assert f"{other.reference} ({other.currency})" not in missing
    assert Message.objects.filter(template="bank_position_missing", person=b.cm).exists()
    assert not BankPosition.objects.filter(escrow=e, as_of=day).exists()  # never invented


def test_new_jobs_are_scheduled():
    """02 section 7.12: the three escrow jobs are on the beat schedule and registered as tasks."""
    from escrow import tasks  # noqa: F401
    from tenmina.celery import app
    from tenmina.celery_schedule import CELERY_BEAT_SCHEDULE

    for name in ("escrow.payee_expiry", "escrow.cooling_off_end", "escrow.reconcile_positions"):
        assert name in CELERY_BEAT_SCHEDULE and name in app.tasks


# ----------------------------------------------------------------- the PDF instruction (FR-ESC-008, 9.1)

def _sent_release(b):
    e = b.ready_purchase("3000.00")
    ins = services.request_release(e, requested_by=b.cm)
    ins = b.approve_all(ins)
    assert ins.status == "sent"
    return ins


def test_instruction_pdf_stored_as_evidence_with_hash(b):
    """FR-ESC-008, 9.1: besides the signed JSON, a PDF is stored as evidence with its SHA-256, and it is
    deterministic: rendering the signed file again gives the same bytes."""
    from core.adapters import get_adapter
    from escrow.pdf import render

    ins = _sent_release(b)
    assert ins.pdf_evidence_id and ins.pdf_sha256 == ins.pdf_evidence.sha256
    assert ins.pdf_evidence.content_type == "application/pdf"
    store = get_adapter("evidence_store")
    pdf = store.get(ins.pdf_evidence.storage_key)
    assert pdf.startswith(b"%PDF") and hashlib.sha256(pdf).hexdigest() == ins.pdf_sha256
    doc = store.get(ins.document_evidence.storage_key)
    again = render(doc, document_sha256=ins.document_sha256)
    assert again == pdf


def test_instruction_pdf_download_needs_release_rights(b, api):
    """FR-ESC-008: staff with release rights download the PDF; the case manager without them and the client
    cannot. Every download is audited."""
    ins = _sent_release(b)
    url = f"/v1/release-instructions/{ins.pk}/pdf"
    r = api(b.rv).get(url)
    assert r.status_code == 200 and r["Content-Type"] == "application/pdf"
    assert r["X-Content-SHA256"] == ins.pdf_sha256
    assert hashlib.sha256(r.content).hexdigest() == ins.pdf_sha256
    assert AuditEvent.objects.filter(action="release.pdf_downloaded", entity_id=str(ins.pk)).exists()
    assert api(b.cm).get(url).status_code == 403
    assert api(b.client).get(url).status_code in (403, 404)


def test_instruction_pdf_not_before_sending(b, api):
    """9.1: the PDF is made when the instruction is sent; before that there is nothing to download."""
    e = b.ready_purchase("3000.00")
    ins = services.request_release(e, requested_by=b.cm)
    assert api(b.rv).get(f"/v1/release-instructions/{ins.pk}/pdf").status_code == 404
