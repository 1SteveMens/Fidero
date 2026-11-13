"""ESC test fixtures. Every module's seed runs once per session and is
committed to the ESC test database (TEST_DB_NAME=test_esc); each test then
runs in its own transaction and is rolled back. Fetch objects fresh by
primary key; never rely on an instance another test may have changed."""
import itertools
from decimal import Decimal

import pytest
from django.utils import timezone


@pytest.fixture(scope="session")
def _esc_media(tmp_path_factory):
    return tmp_path_factory.mktemp("esc-media")


@pytest.fixture(autouse=True)
def _fast(settings, _esc_media):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    settings.MEDIA_ROOT = _esc_media


@pytest.fixture(scope="session")
def _world(django_db_setup, django_db_blocker, _esc_media):
    import importlib

    from django.conf import settings
    from django.test import override_settings

    ctx = {"people": {}}
    with django_db_blocker.unblock(), override_settings(
            MEDIA_ROOT=_esc_media, PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"]):
        for name in settings.TENMINA_MODULES:
            try:
                mod = importlib.import_module(f"{name}.seed")
            except ModuleNotFoundError as exc:
                if exc.name == f"{name}.seed":
                    continue
                raise
            mod.run(ctx)
    return ctx


@pytest.fixture
def seeded(_world, db):
    from accounts.models import Person
    from countries.models import Country

    ctx = dict(_world)
    ctx["people"] = {k: Person.objects.get(pk=p.pk) for k, p in _world["people"].items()}
    ctx["gh"] = Country.objects.get(pk=_world["gh"].pk)
    return ctx


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
            services.record_virtual_account(e, self.cm, virtual_account_ref=f"VA-HF-{_n():06d}")
        e = Escrow.objects.get(pk=e.pk)
        if amount:
            self.deposit(e, amount)
        return Escrow.objects.get(pk=e.pk)

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
