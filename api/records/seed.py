"""REC demo data (R3 pilot): a stool and a family register, the stool secretary
as the authority's representative, allocations in several states (captured,
confirmed, flagged for overlap), an exact match with the chain pre-filled and a
near match for review, and a computed revenue share. The share per case is a
working assumption [TO VERIFY]."""
import json
from datetime import date, timedelta

from django.utils import timezone


def _ev(gh, by, name):
    from evidence.models import Evidence
    from evidence.services import store

    ev = Evidence.objects.filter(original_name=name, country=gh).first()
    return ev or store(data=f"Scanned register page: {name}".encode(), country=gh, uploaded_by=by,
                       content_type="text/plain", original_name=name, data_class="case")


def _shifted(geom, fx):
    g = json.loads(geom.geojson)
    xs = [p[0] for poly in g["coordinates"] for ring in poly for p in ring]
    dx = (max(xs) - min(xs)) * fx
    g["coordinates"] = [[[[p[0] + dx, p[1]] for p in ring] for ring in poly] for poly in g["coordinates"]]
    return g


def run(ctx):
    from administration.models import FeatureFlag
    from cases.models import OPEN_STATUSES, Case

    from . import services
    from .models import Allocation, Authority

    gh, people = ctx["gh"], ctx["people"]
    cm, admin, ar = people["cm"], people["admin"], people["authority"]
    # R3 gate: development only. Production default is off (add records.enabled to 06 2.6).
    FeatureFlag.objects.get_or_create(name=services.FLAG, country=None, defaults={"enabled": True, "owner": "founder"})
    stool = Authority.objects.filter(country=gh, name="Oyarifa Stool (demo)").first() or services.create_authority(
        cm, country=gh, name="Oyarifa Stool (demo)", kind="stool", region="Greater Accra", district="Adenta",
        share_per_case="50.00", agreement_evidence=_ev(gh, cm, "records-agreement-oyarifa-stool.txt"))
    family = Authority.objects.filter(country=gh, name="Nii Odai Family (demo)").first() or services.create_authority(
        cm, country=gh, name="Nii Odai Family (demo)", kind="family", region="Greater Accra", share_per_case="40.00")
    services.add_representative(cm, authority=stool, person=ar, title="Stool secretary",
                                authorisation_evidence=_ev(gh, cm, "stool-letter-of-authority.txt"))
    ctx["records"] = {"stool": stool, "family": family}
    if Allocation.objects.filter(authority=stool).exists():
        return
    from geo.services import save_boundary

    # Land verifications only: a fresh search reuses a released plot whose boundary other journeys rely on.
    cases = list(Case.objects.filter(country=gh, status__in=OPEN_STATUSES, asset__isnull=False, product_line="land")
                 .select_related("asset__current_boundary").order_by("created_at")[:2])
    today = timezone.localdate()
    if not cases:
        return
    for i, c in enumerate(cases):
        if c.asset.current_boundary_id is None:  # a surveyor's drawn boundary near Oyarifa (demo)
            lng, lat, d = -0.1650 - i * 0.004, 5.7300, 0.0012
            save_boundary(c.asset, actor=cm, source="drawn",
                          points=[[lng, lat], [lng + d, lat], [lng + d, lat + d], [lng, lat + d]])
    cases = list(Case.objects.filter(pk__in=[c.pk for c in cases]).select_related("asset__current_boundary")
                 .order_by("created_at"))
    bv = cases[0].asset.current_boundary
    first = services.capture_allocation(cm, authority=stool, reference="Oyarifa stool book 2, p. 17",
                                        allottee_name="Nana Kwaku Asare", allocated_on=date(1998, 3, 2),
                                        document_evidence=_ev(gh, cm, "oyarifa-book2-p17.txt"),
                                        geojson=json.loads(bv.geom.geojson), locality=cases[0].asset.locality)
    later = services.capture_allocation(cm, authority=stool, reference="Oyarifa stool book 3, p. 41",
                                        allottee_name="Kwabena Owusu", allocated_on=date(2014, 6, 20),
                                        document_evidence=_ev(gh, cm, "oyarifa-book3-p41.txt"),
                                        geojson=json.loads(bv.geom.geojson), previous=first,
                                        locality=cases[0].asset.locality)
    services.confirm_allocation(later, ar)
    ctx["records"]["exact"] = later
    if len(cases) > 1:
        bv2 = cases[1].asset.current_boundary
        near = services.capture_allocation(cm, authority=family, reference="Nii Odai family register 1, entry 9",
                                           allottee_name="Esi Darko", allocated_on=date(2009, 1, 15),
                                           document_evidence=_ev(gh, cm, "nii-odai-register-1-9.txt"),
                                           geojson=_shifted(bv2.geom, 0.6))
        ctx["records"]["near"] = near
    # A second family entry over the stool's land: flagged as an overlap for review (US-REC-001 AC2).
    services.capture_allocation(cm, authority=family, reference="Nii Odai family register 1, entry 12",
                                allottee_name="Yaw Mensah", allocated_on=date(2016, 9, 1),
                                document_evidence=_ev(gh, cm, "nii-odai-register-1-12.txt"),
                                geojson=_shifted(bv.geom, 0.3))
    for c in cases:
        for m in services.match_case(c):
            lw = c.tasks.filter(owner_role="LW", assignee__isnull=False).first()
            if m.kind == "exact" and lw is not None:
                try:
                    services.confirm_match(m, lw.assignee, note="Checked against the indenture (demo)")
                except Exception:  # noqa: BLE001 - the demo leaves it proposed if the report is not editable
                    pass
    services.compute_revenue_shares(admin, country=gh, period_start=today.replace(day=1) - timedelta(days=365),
                                    period_end=today)
