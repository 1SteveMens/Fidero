"""CARE test helpers: a fresh plan for the seeded client's mother with the seeded carer, visits whose windows are
now, a registered phone for the carer, and a known confirmation code."""
import itertools
import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

APP = {"HTTP_TENMINA_APP": "field/android/1.0.0"}
ITEMS = [
    {"key": "medicines", "kind": "medicine", "label": "Medicines taken", "photo_allowed": True},
    {"key": "blood_pressure", "kind": "reading", "label": "Blood pressure", "reading_required": True,
     "reading_kind": "blood_pressure"},
    {"key": "groceries", "kind": "groceries", "label": "Groceries delivered", "photo_required": True},
    {"key": "company", "kind": "companionship", "label": "Sit and talk"},
]
_seq = itertools.count(1)


@pytest.fixture(autouse=True)
def _known_code(monkeypatch):
    """Confirmation codes are random; tests know them (the code never reaches any API response)."""
    from notifications import services as ntf

    monkeypatch.setattr(ntf.secrets, "randbelow", lambda n: 123456)


class Care:
    def __init__(self, ctx):
        self.ctx = ctx
        self.gh = ctx["gh"]
        self.p = ctx["people"]
        self.client, self.cm, self.rv, self.rv2 = (self.p["client"], self.p["cm"], self.p["reviewer"],
                                                   self.p["reviewer2"])
        self.mother = ctx["family_members"]["mother"]
        self.carer_person = self.p["carer"]
        from care.models import Carer

        self.carer = Carer.objects.get(person=self.carer_person)
        self._phone = None

    @property
    def phone(self):
        from mobile.devtools import FakePhone

        if self._phone is None:
            self._phone = FakePhone(self.carer_person, model="SM-A145F")
            self._phone.register()
        return self._phone

    def plan(self, *, activate=True, carer=None, items=ITEMS, **kw):
        from care import services
        from orders import legal

        plan = services.create_plan(self.client, client=self.client, family_member_id=self.mother.pk, items=items,
                                    schedule=kw.pop("schedule", {"weekly": ["mon", "thu"], "window": "10:00-12:00"}),
                                    visit_fee={"amount": "150.00", "currency": "GHS"},
                                    confirmers=kw.pop("confirmers", [self.mother.pk]), **kw)
        services.assign_carer(plan, self.cm, carer or self.carer)
        if activate:
            cur = legal.current(self.gh)
            services.activate_plan(plan, self.client, terms_version=cur["terms_version"],
                                   scope_version=cur["scope_version"], mfa_at=timezone.now())
        plan.refresh_from_db()
        return plan

    def visit(self, plan, *, minutes_ago=45, hours=3):
        from care import services
        from care.models import Visit

        start = timezone.now() - timedelta(minutes=minutes_ago) + timedelta(seconds=next(_seq))
        v = Visit.objects.create(country=plan.country, plan=plan, carer=plan.carer, plan_version=plan.version,
                                 window_start=start, window_end=start + timedelta(hours=hours),
                                 fee_amount=plan.visit_fee_amount, fee_currency=plan.visit_fee_currency)
        services._visit_items(v, plan)
        return v

    def check(self, kind, v, *, at=None, lat=None, lng=None, phone=None):
        from mobile.services import record_checkin

        phone = phone or self.phone
        p = v.plan
        ci, _ = record_checkin(phone.person, phone.check(
            kind, "care_visit", v.pk, lat=float(lat if lat is not None else p.point_lat),
            lng=float(lng if lng is not None else p.point_lng), accuracy=6.0, captured_at=at), kind)
        v.refresh_from_db()
        return ci

    def photo(self, v, key="groceries", person=None):
        from mobile.devtools import jpeg
        from mobile.services import complete_item, register_item

        data = jpeg(f"care-test-{uuid.uuid4()}", model=self.phone.model)
        p = v.plan
        m, _ = register_item(self.carer_person, self.phone.capture("care_visit", v.pk, data, requirement_key=key,
                                                                   lat=float(p.point_lat), lng=float(p.point_lng)),
                             app_version="1.0.0")
        m, _ = complete_item(m, self.carer_person, data)
        return m.evidence_id

    def do_items(self, v):
        from care import services

        services.record_item(v, self.carer_person, "medicines", outcome="done")
        services.record_item(v, self.carer_person, "blood_pressure", outcome="done",
                             reading={"systolic": 130, "diastolic": 85})
        services.record_item(v, self.carer_person, "groceries", outcome="done", evidence_id=self.photo(v))
        services.record_item(v, self.carer_person, "company", outcome="not_applicable")

    def checked_out(self, plan=None, **kw):
        """A visit checked in and out at the address with every item answered: the code has gone out."""
        plan = plan or self.plan()
        v = self.visit(plan, **kw)
        now = timezone.now()
        self.check("checkin", v, at=now - timedelta(minutes=40))
        self.do_items(v)
        self.check("checkout", v, at=now - timedelta(minutes=5))
        v.refresh_from_db()
        return v

    def confirm(self, v):
        """The family confirms with the code sent to them (by SMS reply, as a basic phone would)."""
        from notifications.services import confirm_by_reply

        confirm_by_reply(from_address=self.mother.phone, text="123456")
        v.refresh_from_db()
        return v

    def new_carer(self, name="Esi Second Carer", pay_route="held_funds", vetted=True):
        """A second person on the panel (or only vetted, when pay_route is None)."""
        from accounts.models import Person, RoleGrant
        from accounts.services import complete_vetting, create_vetting, request_national_id_check
        from care import services
        from evidence.services import store

        n = next(_seq)
        p = Person.objects.create(email=f"carer{n}-{uuid.uuid4().hex[:6]}@example.com", full_name=f"{name} {n}",
                                  home_country=self.gh, phone=f"+23327{uuid.uuid4().int % 10 ** 7:07d}")
        RoleGrant.objects.create(person=p, role="CE")
        chk = request_national_id_check(by=self.cm, country=self.gh, subject_role="carer", subject_name=p.full_name,
                                        id_number=f"GHA-7{n:08d}-3", person=p)
        ev = store(data=f"refs {n}".encode(), country=self.gh, uploaded_by=self.cm, content_type="text/plain")
        v = create_vetting(self.cm, p, kind="carer", country=self.gh, national_id_check=chk, references_evidence=ev,
                           background_check_evidence=ev)
        if not vetted:
            return p, v
        complete_vetting(v, self.rv)
        if pay_route is None:
            return p, v
        payee = None
        if pay_route == "held_funds":
            payee = self._payee_for(p, chk)
        return services.add_carer(self.cm, person=p, pay_route=pay_route, payee=payee), v

    def _payee_for(self, person, chk):
        from core import approvals
        from escrow import services as esc
        from evidence.services import store

        ev = store(data=f"id {person.pk}".encode(), country=self.gh, uploaded_by=self.cm, content_type="text/plain")
        payee = esc.create_payee(self.cm, country=self.gh, kind="carer", subject_type="person", subject_id=person.pk,
                                 legal_name=person.full_name, legal_name_evidence=ev, bank_name="Demo Bank",
                                 account_number=f"0244{next(_seq):09d}", account_name_source="bank_name_check",
                                 person=person, national_id_check=chk)
        esc.prepare_verification(payee, self.cm)
        payee.refresh_from_db()
        for a in (self.rv, self.rv2):
            approvals.decide(payee.approval_request, a, mfa_at=timezone.now())
            payee.approval_request.refresh_from_db()
        payee.refresh_from_db()
        return payee


@pytest.fixture
def care(seeded):
    return Care(seeded)


@pytest.fixture
def field_api(api):
    def make(person):
        c = api(person)
        c.defaults.update(APP)
        return c

    return make


@pytest.fixture
def topics():
    from core.models import OutboxEvent

    def get(*names, **payload):
        qs = OutboxEvent.objects.filter(topic__in=names)
        for k, v in payload.items():
            qs = qs.filter(**{f"payload__{k}": str(v)})
        return list(qs.values_list("topic", flat=True))

    return get
