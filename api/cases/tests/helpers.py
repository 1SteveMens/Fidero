"""Helpers shared by the CASE and RPT tests."""
import uuid

from core.ids import uuid7
from orders import services as order_services
from orders.tests.helpers import place_order


def paid_case(api, people, gh, who="client", **over):
    """Place an order as `who`, mark it paid as PAY would, and return its case (status paid)."""
    from cases.models import Case

    o = place_order(api(people[who]), people[who], gh, **over)
    order_services.mark_paid(o["id"], payment_id=uuid7(), method="card")
    return Case.objects.get(order_id=o["id"])


def accepted_case(api, people, gh, **over):
    from cases import services

    case = paid_case(api, people, gh, **over)
    services.accept(case, people["cm"])
    case.refresh_from_db()
    return case


def task(case, key):
    return case.tasks.get(step_key=key)


def jpeg(person, gh, name="photo.jpg"):
    from evidence.services import store

    return store(data=b"\xff\xd8\xff\xe0 demo " + name.encode() + uuid7().bytes, country=gh, uploaded_by=person,
                 content_type="image/jpeg", original_name=name)


def pdf(person, gh, name="doc.pdf"):
    from evidence.services import store

    return store(data=b"%PDF-1.4 demo " + name.encode() + uuid7().bytes, country=gh, uploaded_by=person,
                 content_type="application/pdf", original_name=name)


def licensed(gh, role, email, name, *, status="verified", days=200):
    """A new professional with a role and a licence (RUL-20)."""
    from datetime import date, timedelta

    from accounts.models import Person, ProfessionalLicence, RoleGrant

    p = Person.objects.create_user(email, "tenmina-dev-123", full_name=name, home_country=gh)
    RoleGrant.objects.create(person=p, role=role)
    admin = Person.objects.get(email="admin@tenmina.test")
    lic = ProfessionalLicence.objects.create(person=p, role=role, country=gh, body="Demo body",
                                             number=f"DEMO/{uuid.uuid4().hex[:12]}", expires_on=date.today() + timedelta(days=days))
    if status == "verified":
        lic.status, lic.verified_by, lic.verified_on = "verified", admin, date.today()
        lic.save(update_fields=["status", "verified_by", "verified_on"])
    return p
