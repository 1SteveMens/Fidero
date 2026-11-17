"""FR-ESC-001: creating an escrow refuses a missing property with a 422 before
the database constraint esc_asset_required is reached."""
import uuid

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from escrow.models import ASSET_OPTIONAL_KINDS, ESCROW_KINDS, Escrow, ReportSnapshot

ASSET_KINDS = [k for k in ESCROW_KINDS if k not in ASSET_OPTIONAL_KINDS]


def test_asset_kinds_are_the_four_property_kinds():
    assert sorted(ASSET_KINDS) == ["construction", "offplan", "purchase", "repair"]


def _body(b, kind, **extra):
    body = {"kind": kind, "country": "GH", "client_id": str(b.client.pk), "title": f"No property {kind}",
            "agreed_price": {"amount": "1000.00", "currency": "GHS"}}
    if kind in ("construction", "offplan"):
        body["project_id"] = str(uuid.uuid4())  # so the property is the only thing missing
    if kind == "purchase":
        rid = uuid.uuid4()  # a released report whose snapshot names no property
        ReportSnapshot.objects.create(report_id=rid, country=b.gh, client=b.client, verdict="green", asset_id=None,
                                      case_id=uuid.uuid4(), released_at=timezone.now(), conditions=[])
        body["report_id"] = str(rid)
    body.update(extra)
    return body


@pytest.mark.parametrize("kind", ["purchase", "construction", "offplan", "repair"])
def test_create_without_property_is_a_422(b, api, kind):
    before = Escrow.objects.count()
    r = api(b.rv).post("/v1/escrows", _body(b, kind), format="json")
    assert r.status_code == 422, r.content
    body = r.json()
    assert body["code"] == "validation-error"
    assert "needs the property it is for" in body["detail"] and "property ID" in body["detail"]
    assert Escrow.objects.count() == before


def test_repair_with_property_is_created(b, api):
    r = api(b.rv).post("/v1/escrows", _body(b, "repair", asset_id=str(uuid.uuid4())), format="json")
    assert r.status_code == 201, r.content


def test_event_needs_no_property(b, api):
    r = api(b.rv).post("/v1/escrows", _body(b, "event"), format="json")
    assert r.status_code == 201, r.content


def test_database_still_refuses_a_repair_without_property(b):
    """The constraint stays as the backstop when the service is bypassed."""
    e = Escrow.objects.filter(kind="repair").exclude(asset_id=None).first() or Escrow.objects.exclude(
        asset_id=None).first()
    with pytest.raises(IntegrityError), transaction.atomic():
        Escrow.objects.filter(pk=e.pk).update(kind="repair", asset_id=None)
