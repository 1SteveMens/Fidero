"""FR-ESC-001: creating an escrow refuses a missing property or project with a 422
before the database constraints esc_asset_required and esc_project_kinds_have_project
are reached."""
import uuid

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from escrow.models import ASSET_OPTIONAL_KINDS, ESCROW_KINDS, PROJECT_KINDS, Escrow, ReportSnapshot

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


def test_project_kinds_are_the_three_staged_build_kinds():
    assert sorted(PROJECT_KINDS) == ["construction", "offplan", "project_fund"]


def _no_project_body(b, kind, **extra):
    body = {"kind": kind, "country": "GH", "client_id": str(b.client.pk), "title": f"No project {kind}",
            "agreed_price": {"amount": "1000.00", "currency": "GHS"}}
    if kind not in ASSET_OPTIONAL_KINDS:
        body["asset_id"] = str(uuid.uuid4())  # so the project is the only thing missing
    body.update(extra)
    return body


@pytest.mark.parametrize("kind", ["construction", "offplan", "project_fund"])
def test_create_without_project_is_a_422(b, api, kind):
    """FR-ESC-001: a construction, off-plan or project-fund escrow names its project."""
    before = Escrow.objects.count()
    r = api(b.rv).post("/v1/escrows", _no_project_body(b, kind), format="json")
    assert r.status_code == 422, r.content
    body = r.json()
    assert body["code"] == "validation-error"
    assert "needs the project it is for" in body["detail"] and "Enter the project ID." in body["detail"]
    assert "property" not in body["detail"]
    assert Escrow.objects.count() == before


@pytest.mark.parametrize("kind", ["construction", "offplan"])
def test_create_without_property_or_project_names_both(b, api, kind):
    """FR-ESC-001: when both are missing, one message names both, so the client fixes both at once."""
    body = _no_project_body(b, kind)
    del body["asset_id"]
    r = api(b.rv).post("/v1/escrows", body, format="json")
    assert r.status_code == 422, r.content
    assert r.json()["detail"].endswith("needs the property and the project it is for. "
                                       "Enter the property ID and the project ID.")


def test_project_fund_with_project_is_created(b, api):
    r = api(b.rv).post("/v1/escrows", _no_project_body(b, "project_fund", project_id=str(uuid.uuid4())),
                       format="json")
    assert r.status_code == 201, r.content


def test_database_still_refuses_a_project_fund_without_project(b):
    """The constraint stays as the backstop when the service is bypassed."""
    e = Escrow.objects.exclude(project_id=None).first()
    with pytest.raises(IntegrityError), transaction.atomic():
        Escrow.objects.filter(pk=e.pk).update(kind="project_fund", project_id=None)
