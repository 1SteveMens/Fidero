from datetime import timedelta

import pytest
from django.utils import timezone


@pytest.fixture
def pmg(seeded):
    return seeded["pmg"]


@pytest.fixture
def doc(gh):
    from evidence.services import store

    def make(by, name="document.txt", image=False):
        if image:
            from mobile.devtools import jpeg

            return store(data=jpeg(f"pmg-test-{name}-{timezone.now().timestamp()}"), country=gh, uploaded_by=by,
                         content_type="image/jpeg", original_name=f"{name}.jpg")
        return store(data=f"{name} {timezone.now().timestamp()}".encode(), country=gh, uploaded_by=by,
                     content_type="text/plain", original_name=name)

    return make


@pytest.fixture
def phone(pmg):
    from propertymgmt.seed import _phone

    return _phone(pmg["inspector"], "inspector")


@pytest.fixture
def snap(phone):
    """snap(inspection, key) -> an app-captured photo of that inspection (RUL-08)."""
    from propertymgmt.seed import capture

    counter = {"n": 0}

    def take(insp, key="room_front"):
        counter["n"] += 1
        return capture(phone, insp, key, f"test-{key}-{counter['n']}-{timezone.now().timestamp()}")

    return take


@pytest.fixture
def new_property(gh, people, doc):
    from propertymgmt import services

    def make(owner=None, title="Test house"):
        owner = owner or people["client"]
        return services.register_property(owner, country=gh, title=title, locality="Spintex",
                                          ownership_evidence_ids=[doc(owner, "title.txt").pk])

    return make


@pytest.fixture
def onboard(gh, people, seeded, pmg, snap):
    """Take a registered property to managed: rent account, condition inspection with photos, ownership check."""
    from propertymgmt import services
    from propertymgmt.seed import _close_case

    def run(prop, close_case=True):
        services.set_rent_account(prop, prop.owner, seeded["bank_accounts"]["rent"].pk)
        insp = services.onboarding_inspection(prop)
        services.assign_inspector(insp, people["cm"], pmg["inspector"])
        ph = snap(insp)
        services.record_inspection(insp, pmg["inspector"], outcome="pass", condition_rating="good",
                                   rooms=[{"room": "Front", "evidence_ids": [str(ph.pk)]}])
        if close_case:
            _close_case(prop.onboarding_case, people["cm"], people["reviewer"])
        prop.refresh_from_db()
        return prop

    return run


@pytest.fixture
def mandate(people, doc):
    from propertymgmt import services

    def make(prop, valid_from=None):
        m = services.record_mandate(prop, prop.owner, mandate_evidence_id=doc(prop.owner, "mandate.txt").pk,
                                    valid_from=valid_from or timezone.localdate() - timedelta(days=200))
        return services.acknowledge_mandate(m, people["cm"], evidence_id=doc(people["cm"], "ack.txt").pk)

    return make


@pytest.fixture
def tenancy(people, doc):
    from propertymgmt import services

    def make(prop, starts_on=None, ref="TEST-REF-1", tenant=None):
        tenant = tenant or people["tenant"]
        return services.record_tenancy(prop, people["cm"], tenant_email=tenant.email, tenant_name=tenant.full_name,
                                       agreement_evidence_id=doc(people["cm"], "agreement.txt").pk,
                                       rent={"amount": "2000.00", "currency": "GHS"}, period="monthly", due_day=5,
                                       starts_on=starts_on or timezone.localdate().replace(day=1) - timedelta(days=62),
                                       tenant_reference=ref)

    return make


def statement(account, rows):
    lines = ["account_number,booked_on,kind,amount,currency,bank_reference,counterparty_name,narrative"]
    for r in rows:
        lines.append(",".join([r.get("account", account), r["on"].isoformat(), r.get("kind", "credit"), r["amount"],
                               "GHS", r["ref"], "TENANT", r.get("text", "")]))
    return "\n".join(lines) + "\n"
