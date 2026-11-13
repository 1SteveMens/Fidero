"""Helpers for the FEE tests."""
import base64
from decimal import Decimal

from django.utils import timezone

from core.ids import uuid7


def doc(person, gh, name="bill.pdf", ct="application/pdf"):
    from evidence.services import store

    head = b"\xff\xd8\xff\xe0 " if ct == "image/jpeg" else b"%PDF-1.4 "
    return store(data=head + name.encode() + uuid7().bytes, country=gh, uploaded_by=person, content_type=ct,
                 original_name=name)


def b64doc(name="bill.pdf"):
    return base64.b64encode(b"%PDF-1.4 " + name.encode() + uuid7().bytes).decode()


def new_institution(gh, people, name=None, *, account=None, client=None, type="hospital", contact=True,
                    contact_person=None, returns_confirmation=False):
    """A fully verified institution: registration case verified, payee verified by two staff, a named contact."""
    import random

    from fees.seed import verified_institution

    n = uuid7().hex[-6:]
    return verified_institution(gh, people, name=name or f"Test Hospital {n}", type=type, reg=f"REG/{n}",
                                account=account or f"12{random.randint(10**10, 10**11 - 1)}1",
                                contact_name="" if contact_person else "Mary Contact", contact_person=contact_person,
                                contact_phone=f"+23330{random.randint(10**6, 10**7 - 1)}",
                                nid=f"GHA-7{random.randint(10**7, 10**8 - 1)}-{random.randint(1, 8)}",
                                client=client, returns_confirmation=returns_confirmation, with_contact=contact)


def contact_person(email=None):
    """A person who will hold role IC once named as a contact."""
    from accounts.models import Person

    return Person.objects.create_user(email or f"ic-{uuid7().hex[-8:]}@example.com", "tenmina-dev-123",
                                      full_name="Abena Accounts", phone=f"+23324{uuid7().int % 10**7:07d}")


def checked_invoice(gh, people, inst, fm=None, amount="500.00", ref=None, client=None, **kw):
    from fees import services

    client = client or people["client"]
    fm = fm or client.family_members.filter(status="active").first()
    inv = services.submit_invoice(client, institution=inst, family_member=fm,
                                  institution_reference=ref or f"INV-{uuid7().hex[-8:]}", amount=amount,
                                  currency="GHS", evidence=doc(client, gh), **kw)
    contact = inst.contacts.filter(status="active").first()
    return services.check_invoice(inv, people["cm"], outcome="checked", contact=contact, note="Confirmed by phone")


def approve(inv, client, **kw):
    from fees import services

    return services.client_approve(inv, client, mfa_at=timezone.now(),
                                   confirm_amount={"amount": str(inv.amount), "currency": inv.currency},
                                   confirm_payee_account_name=inv.institution.payee.account_name, **kw)


def fund_held(client, gh, amount="20000.00"):
    """The client's held funds escrow, with a bank-confirmed deposit (FR-ESC-014)."""
    from escrow import services as esc
    from escrow.models import Escrow
    from escrow.seed import _deposit

    from django.contrib.auth import get_user_model

    Person = get_user_model()
    cm = Person.objects.get(email="cm@tenmina.test")
    rv = Person.objects.get(email="rv1@tenmina.test")
    e = esc.held_funds_for(client, gh, "GHS")
    if e is None:
        e = esc.open_held_funds(client, gh, "GHS", by=client)
        esc.record_virtual_account(e, cm, virtual_account_ref=f"VA-T-{uuid7().hex[-8:]}")
    if Decimal(amount) > 0:
        _deposit(Escrow.objects.get(pk=e.pk), cm, rv, amount, f"DEP-T-{uuid7().hex[-8:]}")
    return Escrow.objects.get(pk=e.pk)


def staff_approve_and_confirm(ins, people):
    from escrow import services as esc
    from escrow.seed import _confirm

    esc.staff_approve(ins, people["reviewer"], mfa_at=timezone.now())
    esc.staff_approve(ins, people["reviewer2"], mfa_at=timezone.now())
    ins.refresh_from_db()
    assert ins.status == "sent", ins.status
    return _confirm(ins, people["cm"], people["reviewer"], f"PAY-T-{uuid7().hex[-8:]}")
