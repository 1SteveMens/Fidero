"""TSK test helpers: funded errands for the seeded client, the seeded agent and agency, captures from the agent's
phone, and new agents."""
import itertools
import uuid

import pytest
from django.utils import timezone

APP = {"HTTP_TENMINA_APP": "field/android/1.0.0"}
_seq = itertools.count(1)


def pdf(name="doc"):
    return f"%PDF-1.4\n% {name} {uuid.uuid4()}\n".encode()


class Tsk:
    def __init__(self, ctx):
        self.ctx = ctx
        self.gh = ctx["gh"]
        self.p = ctx["people"]
        self.client, self.cm, self.rv = self.p["client"], self.p["cm"], self.p["reviewer"]
        refs = ctx["errands"]
        from errands.models import Agent
        from escrow.models import Payee

        self.agent = Agent.objects.get(pk=refs["agent"].pk)
        self.agent_person = self.agent.person
        self.agency = Payee.objects.get(pk=refs["agency_payee"].pk)
        self._phone = None

    @property
    def phone(self):
        from mobile.devtools import FakePhone

        if self._phone is None:
            self._phone = FakePhone(self.agent_person, model="SM-A145F")
            self._phone.register()
        return self._phone

    def terms(self):
        from orders import legal

        cur = legal.current(self.gh)
        return {"terms_version": cur["terms_version"], "scope_version": cur["scope_version"]}

    def ev(self, name="doc", by=None):
        from evidence.services import store

        return store(data=pdf(name), country=self.gh, uploaded_by=by or self.client, content_type="application/pdf",
                     data_class="identity_documents")

    def errand(self, code="birth_cert", *, upload=True, submit=True, accept=True, pay=True, **kw):
        from errands import services
        from orders.services import mark_paid

        e = services.create_errand(self.client, country=self.gh, code=code, **kw)
        if upload:
            for d in e.documents.all():
                services.upload_document(e, self.client, d.key, evidence=self.ev(d.key))
        if submit:
            services.submit_errand(e, self.client, **self.terms())
        if accept:
            for d in e.documents.all():
                services.review_document(d, self.cm, accept=True)
        e.refresh_from_db()
        if pay:
            mark_paid(e.fee_order_id, payment_id=uuid.uuid4(), method="card")
        e.refresh_from_db()
        return e

    def assigned(self, code="birth_cert", **kw):
        from errands import services

        e = self.errand(code, **kw)
        assert e.status == "funded", services.funding_blockers(e)
        return services.assign(e, self.cm, agent=self.agent,
                               agency_payee=self.agency if e.official_fees_amount > 0 else None)

    def photo(self, subject_type, subject_id, key="receipt", data=None):
        from mobile.devtools import jpeg
        from mobile.services import complete_item, register_item

        data = data or jpeg(f"errand-test-{uuid.uuid4()}", model=self.phone.model)
        m, _ = register_item(self.agent_person, self.phone.capture(subject_type, subject_id, data,
                                                                   requirement_key=key, lat=5.5560, lng=-0.1969),
                             app_version="1.0.0")
        m, _ = complete_item(m, self.agent_person, data)
        return m.evidence_id

    def new_agent(self, *, agreement=True, vetted=True):
        from accounts.models import Person, RoleGrant
        from accounts.services import complete_vetting, create_vetting, request_national_id_check
        from errands import services

        n = next(_seq)
        p = Person.objects.create(email=f"agent{n}-{uuid.uuid4().hex[:6]}@example.com", full_name=f"Agent {n}",
                                  home_country=self.gh, phone=f"+23328{uuid.uuid4().int % 10 ** 7:07d}")
        RoleGrant.objects.create(person=p, role="CE")
        chk = request_national_id_check(by=self.cm, country=self.gh, subject_role="errand_agent",
                                        subject_name=p.full_name, id_number=f"GHA-8{n:08d}-4", person=p)
        v = create_vetting(self.cm, p, kind="errand_agent", country=self.gh, national_id_check=chk,
                           references_evidence=self.ev("refs", self.cm),
                           background_check_evidence=self.ev("police", self.cm))
        if not vetted:
            return p, v
        complete_vetting(v, self.rv)
        return services.add_agent(self.cm, person=p, pro_agreement_id=uuid.uuid4() if agreement else None)


@pytest.fixture
def tsk(seeded):
    return Tsk(seeded)


@pytest.fixture
def field_api(api):
    def make(person):
        c = api(person)
        c.defaults.update(APP)
        return c

    return make


@pytest.fixture
def now():
    return timezone.now
