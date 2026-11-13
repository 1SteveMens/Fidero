"""Short ways to reach each project state through the real services (BLD and PRJ tests)."""
import itertools
import uuid
from datetime import timedelta

from django.utils import timezone

_n = itertools.count(1)


class Builder:
    def __init__(self, ctx):
        self.ctx = ctx
        self.gh = ctx["gh"]
        self.p = ctx["people"]
        self.cm, self.rv, self.rv2 = self.p["cm"], self.p["reviewer"], self.p["reviewer2"]
        self.client = self.p["client"]
        self.panel = ctx["construction"]["panel"]

    def m(self, key):
        from construction.models import PanelMember

        return PanelMember.objects.get(pk=self.panel[key].pk)

    def ev(self, name="doc", by=None, kind="application/pdf"):
        from evidence.services import store

        data = f"%PDF-1.4 {name} {next(_n)} {uuid.uuid4()}".encode()
        if kind == "image/jpeg":
            data = b"\xff\xd8\xff\xe0" + data
        return store(data=data, country=self.gh, uploaded_by=by or self.cm, content_type=kind,
                     original_name=f"{name}.pdf")

    def asset(self):
        from geo.models import Asset

        return Asset.objects.get(pk=self.ctx["report"].case.asset_id)

    def project(self, route="client_direct", contractor="mensah", inspector="esi", start=True, items=None):
        from construction import projects
        from construction.models import Project

        p = projects.create_project(self.cm, type="construction", title=f"Test build {next(_n)}",
                                    asset_id=self.asset().pk, budget="100000.00", client=self.client,
                                    payment_route=route)
        projects.assign_quantity_surveyor(p, self.cm, self.panel["qs"].pk)
        projects.submit_boq(p, self.p["qs"], items=items or [{"description": "The whole house", "amount": "100000.00"}],
                            evidence_ids=[self.ev("boq", by=self.p["qs"]).pk])
        projects.choose_contractor(p, self.client, self.panel[contractor].pk)
        projects.approve_budget(p, self.client)
        if inspector:
            projects.assign_inspector(p, self.cm, self.panel[inspector].pk)
        if start:
            projects.sign_contract(p, self.cm, evidence_ids=[self.ev("contract").pk])
            if route == "escrow":
                self.fund(p)
        return Project.objects.get(pk=p.pk)

    def fund(self, p):
        from construction import projects
        from escrow import services as esc
        from escrow.models import Escrow, Party
        from escrow.seed import _deposit

        projects.open_escrow(p, self.cm)
        p.refresh_from_db()
        e = Escrow.objects.get(pk=p.escrow_id)
        for party in Party.objects.filter(escrow=e, must_accept=True):
            esc.accept_terms(e, self.cm if party.role == "tenmina" else party.person, party=party)
        e.refresh_from_db()
        if e.status == "proposed":
            esc.record_virtual_account(e, self.cm, virtual_account_ref=f"VA-T-BLD-{next(_n):06d}-{uuid.uuid4().hex[:4]}")
        _deposit(Escrow.objects.get(pk=e.pk), self.cm, self.rv, f"{p.budget_amount:.2f}", f"DEP-T-{uuid.uuid4().hex[:8]}")

    def ms(self, p, key):
        from construction.models import Milestone

        return Milestone.objects.get(project=p, key=key)

    def pay_for(self, m, part="main"):
        from construction.models import Payment

        return Payment.objects.filter(milestone=m, part=part).order_by("-created_at").first()

    def approve(self, pay, client=True):
        from construction import payments

        if client:
            payments.client_approve(pay, pay.project.client, mfa_at=timezone.now())
        for a in (self.rv, self.rv2):
            pay.refresh_from_db()
            if pay.status == "client_approved":
                payments.staff_decide(pay, a, mfa_at=timezone.now())
        pay.refresh_from_db()
        return pay

    def settle(self, pay):
        """client_direct: the client pays and the builder confirms; escrow: the bank confirms."""
        from construction import payments

        pay.refresh_from_db()
        if pay.route == "client_direct":
            payments.record_client_payment(pay, pay.project.client, reference=f"REF-{next(_n)}")
            payments.confirm_receipt(pay, self.cm, evidence=self.ev("receipt"))
        else:
            from escrow.seed import _confirm

            _confirm(pay.instruction, self.cm, self.rv, f"PAY-T-{uuid.uuid4().hex[:8]}")
        pay.refresh_from_db()
        return pay

    def mobilise(self, p):
        from construction import projects

        projects.confirm_handover(p, self.cm)
        pay = self.pay_for(self.ms(p, "mobilisation"))
        return self.settle(self.approve(pay))

    def submit(self, m, person=None, when=None):
        from mobile.devtools import jpeg, mp4
        from mobile.seed import _item, _phone
        from mobile.services import submit

        person = person or m.project.contractor.person
        phone = _phone(person, f"bld-test-{person.pk}", platform="android")
        when = when or timezone.now() - timedelta(minutes=10)
        items = []
        for n, req in enumerate(m.required_evidence):
            seed = f"t-{m.pk}-{n}-{uuid.uuid4()}"
            data = mp4(seed) if req["media"] == "video" else jpeg(seed, model=phone.model)
            it = _item(phone, str(uuid.uuid4()), "milestone", m.pk, data, requirement_key=req["key"],
                       media_type="video/mp4" if req["media"] == "video" else "image/jpeg",
                       captured_at=when + timedelta(seconds=n), lat=5.5342, lng=-0.4256)
            items.append({"requirement_key": req["key"], "evidence_id": str(it.evidence_id)})
        submit(person, client_submission_id=str(uuid.uuid4()), subject_type="milestone", subject_id=m.pk,
               items=items)
        m.refresh_from_db()
        return m

    def inspect(self, m, outcome="pass", defects=(), person=None):
        from construction.models import Inspection
        from mobile.devtools import jpeg
        from mobile.seed import _item, _phone
        from mobile.services import submit_inspection

        i = Inspection.objects.get(milestone=m, status="scheduled")
        person = person or i.inspector.person
        phone = _phone(person, f"bld-test-insp-{person.pk}", platform="ios")
        clean = []
        for n, (desc, value) in enumerate(defects):
            it = _item(phone, str(uuid.uuid4()), "milestone_inspection", i.pk,
                       jpeg(f"d-{uuid.uuid4()}", model=phone.model, make="Apple"), requirement_key=f"defect_{n + 1}",
                       captured_at=timezone.now() - timedelta(minutes=1), lat=5.5342, lng=-0.4256)
            clean.append({"description": desc, "value": {"amount": value, "currency": "GHS"},
                          "evidence_ids": [str(it.evidence_id)]})
        submit_inspection(person, client_submission_id=str(uuid.uuid4()), subject_type="milestone_inspection",
                          subject_id=i.pk, outcome=outcome, reason="Not to the drawings" if outcome == "fail" else "",
                          checklist=[{"key": c["key"], "result": "ok"} for c in i.checklist], defects=clean)
        m.refresh_from_db()
        return m

    def to_inspected(self, p, key="foundation", outcome="pass", defects=()):
        from construction import milestones

        m = self.submit(self.ms(p, key))
        milestones.review_evidence(m, self.cm, decision="accept")
        return self.inspect(self.ms(p, key), outcome=outcome, defects=defects)


    def capture(self, person, subject_type, subject_id):
        """An app-captured photo from Tenmina Field (RUL-08)."""
        from evidence.models import Evidence
        from mobile.devtools import jpeg
        from mobile.seed import _item, _phone

        phone = _phone(person, f"bld-test-{person.pk}", platform="android")
        it = _item(phone, str(uuid.uuid4()), subject_type, subject_id, jpeg(f"c-{uuid.uuid4()}", model=phone.model),
                   captured_at=timezone.now() - timedelta(minutes=1), lat=5.5342, lng=-0.4256)
        return Evidence.objects.get(pk=it.evidence_id)
