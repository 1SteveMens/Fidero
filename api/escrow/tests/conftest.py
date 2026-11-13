"""ESC test helpers. Seeds load once per session (api/conftest.py); fetch
objects fresh by primary key rather than relying on an instance another
test may have changed."""
import itertools
from decimal import Decimal

import pytest
from django.utils import timezone


_seq = itertools.count(1)


def _n():
    return next(_seq)


class Builder:
    """Short ways to reach each state through the real services."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.gh = ctx["gh"]
        self.p = ctx["people"]
        self.cm, self.rv, self.rv2 = self.p["cm"], self.p["reviewer"], self.p["reviewer2"]
        self.client = self.p["client"]
        self.now = timezone.now

    def ev(self, name="doc", by=None):
        from evidence.services import store

        return store(data=f"Evidence {name} {_n()}".encode(), country=self.gh, uploaded_by=by or self.cm,
                     content_type="text/plain", original_name=f"{name}.txt", data_class="escrow_payment")

    def payee(self, key):
        from escrow.models import Payee

        return Payee.objects.get(pk=self.ctx["escrow"]["payees"][key].pk)

    def report(self, verdict="green", conditions=2):
        import uuid

        from escrow.models import ReportSnapshot

        rid = uuid.uuid4()
        ReportSnapshot.objects.create(report_id=rid, country=self.gh, client=self.client, verdict=verdict,
                                      asset_id=uuid.uuid4(), case_id=uuid.uuid4(), released_at=timezone.now(),
                                      conditions=[{"id": str(uuid.uuid4()), "text": f"Condition {i + 1}"}
                                                  for i in range(conditions)])
        return rid

    def purchase(self, price="100000.00", conditions=1, held_back="0", held_back_condition=""):
        from escrow import services

        seller = self.payee("seller")
        return services.create_escrow(
            self.cm, kind="purchase", client=self.client, country=self.gh, agreed_amount=price,
            title=f"Test plot {_n()}", report_id=self.report(conditions=conditions),
            held_back_amount=held_back, held_back_condition=held_back_condition,
            parties=[{"role": "seller", "person": self.p["seller"], "name": "Ato Estates Ltd", "payee": seller,
                      "national_id_check": seller.national_id_check}])

    def agree(self, e):
        from escrow import services
        from escrow.models import Escrow, Party

        for party in Party.objects.filter(escrow=e, must_accept=True):
            if party.role == "tenmina":
                services.accept_terms(e, self.cm, party=party)
            elif party.person_id:
                services.accept_terms(e, party.person, party=party)
        services.record_virtual_account(e, self.cm, virtual_account_ref=f"VA-T-{_n():06d}")
        return Escrow.objects.get(pk=e.pk)

    def deposit(self, e, amount, *, currency=None, ref=None, known=True, check=True, misdirected=False,
                route="", partner=None, va=None, name="AMA MENSAH", number="GB000000001"):
        from escrow import services

        ev = services.record_bank_event(
            e, kind="deposit", amount=amount, currency=currency, bank_reference=ref or f"DEP-{_n()}", by=self.cm,
            proof_evidence=self.ev("credit-advice"), source_account_known=known,
            source_bank_name="NatWest" if known else "", source_account_number=number if known else "",
            source_account_name=name if known else "", misdirected=misdirected, deposit_route=route,
            transfer_partner=partner, virtual_account_ref=va)
        return services.check_bank_event(ev, self.rv) if check else ev

    def close_all(self, e, part="main"):
        from escrow import services

        for c in e.conditions.filter(status="open", release_part=part):
            services.close_condition(c, self.cm, evidence_ids=[self.ev("condition").pk])

    def fresh(self, e, days_ago=0):
        from datetime import timedelta

        from escrow import services

        d = timezone.localdate() - timedelta(days=days_ago)
        services.record_fresh_search(e, self.cm, case_id=e.pk, registry_result_date=d, site_check_date=d)

    def ready_purchase(self, price="100000.00", **kw):
        from escrow.models import Escrow

        e = self.agree(self.purchase(price, **kw))
        self.deposit(e, price)
        e = Escrow.objects.get(pk=e.pk)
        self.close_all(e)
        self.fresh(e)
        return Escrow.objects.get(pk=e.pk)

    def new_client(self):
        from accounts.models import Person, RoleGrant

        n = _n()
        p = Person.objects.create(email=f"client{n}-{timezone.now().timestamp()}@example.com",
                                  full_name=f"Test Client {n}", id_check_status="passed", home_country=self.gh)
        RoleGrant.objects.create(person=p, role="CL")
        return p

    def held_funds(self, amount="5000.00", client=None):
        from escrow import services
        from escrow.models import Escrow

        client = client or self.new_client()
        e = services.held_funds_for(client, self.gh, "GHS")
        if e is None:
            e = services.open_held_funds(client, self.gh, "GHS", by=client)
        if not e.virtual_account_ref:
            services.record_virtual_account(e, self.cm, virtual_account_ref=f"VA-HF-{_n():06d}")
        e = Escrow.objects.get(pk=e.pk)
        if amount:
            self.deposit(e, amount)
        return Escrow.objects.get(pk=e.pk)

    # ---- real subjects from the line modules (no made-up subject ids)

    def family_member(self, client):
        from accounts.models import FamilyMember
        from accounts.services import add_family_member

        fm = FamilyMember.objects.filter(client=client).first()
        return fm or add_family_member(client, {"full_name": f"Kojo Test {_n()}", "relationship": "son"})

    def school(self):
        """The seeded Accra Hills School: a verified FEE institution paid through the `school` payee."""
        from fees.models import Institution

        return Institution.objects.get(payee=self.payee("school"))

    def fee_invoice(self, client, amount, approve=True):
        """A real FEE bill (FR-FEE-002, FR-FEE-003): submitted, checked with the school's named contact, on the
        held-funds route and approved by the client with a fresh step-up. When the money is held at the bank,
        FEE prepares the release itself (`fee_release`); otherwise the bill waits for it."""
        from evidence.services import store
        from fees import services as fees
        from fees.models import Invoice

        inst = self.school()
        bill = store(data=f"%PDF-1.4 bill {_n()} {timezone.now().timestamp()}".encode(), country=self.gh,
                     uploaded_by=self.cm, content_type="application/pdf", original_name="bill.pdf")
        inv = fees.submit_invoice(self.cm, institution=inst, family_member=self.family_member(client),
                                  institution_reference=f"T-{_n()}-{int(timezone.now().timestamp() * 1000)}",
                                  amount=amount, currency="GHS", evidence=bill, description="Term fees")
        fees.set_route(inv, self.cm, "held_funds", reason="test")
        fees.check_invoice(Invoice.objects.get(pk=inv.pk), self.cm, outcome="checked",
                           contact=inst.contacts.filter(status="active").first(), resolve_flags=True)
        inv = Invoice.objects.get(pk=inv.pk)
        if not approve:
            return inv
        fees.client_approve(inv, client, mfa_at=timezone.now(),
                            confirm_amount={"amount": str(inv.amount), "currency": inv.currency},
                            confirm_payee_account_name=inst.payee.account_name)
        return Invoice.objects.get(pk=inv.pk)

    def fee_release(self, hf, amount):
        """The release FEE prepares for a real bill paid from this amount held at the bank. With the money
        already there, FEE prepares it when the client approves the bill (the client's approval applies to it);
        otherwise the bank's deposit of the amount lets FEE prepare it, and the client then approves it."""
        from escrow.models import Escrow, ReleaseInstruction

        inv = self.fee_invoice(hf.client, amount)
        pay = inv.payments.filter(route="held_funds").exclude(release_instruction=None).first()
        if pay is None:
            self.deposit(Escrow.objects.get(pk=hf.pk), amount)
            pay = inv.payments.filter(route="held_funds").exclude(release_instruction=None).first()
        assert pay is not None, f"FEE did not prepare the release for {inv.pk} ({inv.status})"
        return ReleaseInstruction.objects.get(pk=pay.release_instruction_id)

    def approve_all(self, ins, client=True):
        from escrow import services

        now = timezone.now()
        if client and ins.status == "awaiting_client":
            services.client_approve(ins, ins.escrow.client, now)
        services.staff_approve(ins, self.rv, mfa_at=now)
        services.staff_approve(ins, self.rv2, mfa_at=now)
        ins.refresh_from_db()
        return ins

    def confirm(self, ins, amount=None):
        from escrow import services

        kind = {"cancel_refund": "refund_confirmed", "conversion": "conversion_debit"}.get(ins.kind,
                                                                                            "release_confirmed")
        ev = services.record_bank_event(ins.escrow, kind=kind, amount=amount or ins.amount, currency=ins.currency,
                                        bank_reference=f"PAY-{_n()}", by=self.cm, instruction=ins,
                                        proof_evidence=self.ev("debit-advice"),
                                        virtual_account_ref=None if ins.currency == ins.escrow.currency else
                                        ins.escrow.fx_accounts.get(currency=ins.currency).virtual_account_ref)
        services.check_bank_event(ev, self.rv)
        ins.refresh_from_db()
        return ins


@pytest.fixture
def b(seeded):
    return Builder(seeded)


@pytest.fixture
def codes():
    def get(exc):
        return {r.get("code") for r in getattr(exc, "blocking_reasons", [])}

    return get


@pytest.fixture
def now():
    return timezone.now


D = Decimal
