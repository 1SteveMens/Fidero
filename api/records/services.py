"""REC Records programme: the public interface other modules may call (FR-REC-001 to FR-REC-004).

    create_authority / add_representative / revoke_representative
    capture_allocation(by, *, authority, reference, allottee_name, allocated_on, document_evidence, points|geojson)
    confirm_allocation(alloc, by) / dispute_allocation(alloc, by, reason)   the authority's representative (AR)
    resolve_overlap(overlap, by, note)
    match_case(case) -> [Match]           runs on asset.boundary_saved and case.status_changed
    confirm_match(match, by) / reject_match(match, by, note)   the lawyer confirms the pre-filled chain
    compute_revenue_shares(by, *, period_start, period_end, authority=None) -> [RevenueShare]
    approve_share / mark_share_paid

Behind `records.enabled` (R3). Events published: record.matched (and <entity>.status_changed).
"""
import logging
from datetime import date
from decimal import Decimal

from django.db import connection, transaction
from django.utils import timezone

from administration import flags
from audit.services import record
from core import state
from core.errors import Forbidden, Invalid, NotFound, SameApprover, StateConflict
from core.events import publish
from core.money import q
from core.permissions import has_role

from .models import (Allocation, AllocationOverlap, Allottee, Authority, Match, Representative, RevenueShare,
                     RevenueShareItem)

log = logging.getLogger(__name__)
FLAG = "records.enabled"
EXACT = Decimal("0.90")  # share of both plot and record for an exact match [TO VERIFY]
NEAR = Decimal("0.05")  # smallest overlap worth a review [TO VERIFY]
USED = ("confirmed",)


def _now():
    return timezone.now()


def _on(country):
    flags.require(FLAG, country)
    flags.read_only_guard()


def _audit(actor, action, obj, data=None):
    record(actor=actor, action=action, entity=obj.__class__.__name__.lower(), entity_id=obj.pk, data=data or {},
           country=getattr(obj, "country", None))


def _notify(person, template, body, *, obj=None, link="", needs_action=False):
    from notifications.services import notify

    if person is None:
        return
    try:
        notify(person, template, body=body, subject_obj=obj, link=link, needs_action=needs_action, category="task")
    except Exception:  # noqa: BLE001
        log.exception("notification %s failed", template)


def _staff_in(country, *roles):
    from django.db.models import Q

    from accounts.models import Person

    return Person.objects.filter(Q(role_grants__country__isnull=True) | Q(role_grants__country=country),
                                 role_grants__role__in=roles, role_grants__revoked_at__isnull=True).distinct()


def is_staff(user, country) -> bool:
    return has_role(user, "CM", "RV", "AD", country=country)


def represents(user, authority) -> bool:
    return bool(user and user.is_authenticated and has_role(user, "AR") and Representative.objects.filter(
        authority=authority, person=user, active=True).exists())


def authority_ids_of(user):
    return list(Representative.objects.filter(person=user, active=True).values_list("authority_id", flat=True))


def can_view_authority(user, authority) -> bool:
    return is_staff(user, authority.country) or represents(user, authority)


def _cfg(country, key, default):
    from countries.selectors import config

    v = config(country, key, None)
    return Decimal(str(v)) if v not in (None, "") else default


# =========================================================================== authorities

@transaction.atomic
def create_authority(by, *, country, name, kind, region="", district="", share_per_case="0",
                     agreement_evidence=None) -> Authority:
    _on(country)
    if not has_role(by, "CM", "AD", country=country):
        raise Forbidden("Only a case manager or administrator records an authority.")
    if Authority.objects.filter(country=country, name__iexact=name.strip()).exists():
        raise StateConflict("This authority is already on the register.")
    a = Authority.objects.create(country=country, name=name.strip(), kind=kind, region=region or "",
                                 district=district or "", share_per_case=q(share_per_case),
                                 share_currency=country.currency, agreement_evidence=agreement_evidence,
                                 created_by=by)
    _audit(by, "rec_authority.created", a, {"kind": kind})
    return a


@transaction.atomic
def update_authority(a: Authority, by, **fields) -> Authority:
    if not has_role(by, "AD", country=a.country):
        raise Forbidden("Only an administrator changes an authority's terms.")
    for k in ("name", "region", "district", "status"):
        if k in fields and fields[k] is not None:
            setattr(a, k, fields[k])
    if fields.get("share_per_case") is not None:
        a.share_per_case = q(fields["share_per_case"])
    a.save()
    _audit(by, "rec_authority.updated", a, {k: str(v) for k, v in fields.items()})
    return a


@transaction.atomic
def add_representative(by, *, authority, person, title="", authorisation_evidence=None) -> Representative:
    """FR-REC-004: only a person holding the AR role, with the authority's written authorisation."""
    _on(authority.country)
    if not has_role(by, "CM", "AD", country=authority.country):
        raise Forbidden("Only a case manager or administrator adds a representative.")
    if not person.has_tenmina_role("AR"):
        raise Invalid("The person must hold the authority representative role.", code="validation-error")
    if authorisation_evidence is None:
        raise Invalid("Attach the authority's written authorisation.", code="validation-error")
    r, created = Representative.objects.get_or_create(
        authority=authority, person=person, active=True,
        defaults={"country": authority.country, "title": title or "", "authorisation_evidence": authorisation_evidence,
                  "granted_by": by})
    if created:
        _audit(by, "rec_representative.added", r, {"authority": str(authority.pk)})
    return r


@transaction.atomic
def revoke_representative(r: Representative, by) -> Representative:
    if not has_role(by, "CM", "AD", country=r.country):
        raise Forbidden()
    r.active, r.revoked_at = False, _now()
    r.save(update_fields=["active", "revoked_at"])
    _audit(by, "rec_representative.revoked", r)
    return r


# =========================================================================== allocations (FR-REC-001)

def _area(geom) -> Decimal:
    with connection.cursor() as cur:
        cur.execute("SELECT ST_Area(ST_GeomFromEWKT(%s)::geography)", [geom.ewkt])
        return Decimal(str(cur.fetchone()[0])).quantize(Decimal("0.01"))


def _shares(a, b) -> tuple[Decimal, Decimal]:
    """(share of a covered by b, share of b covered by a), by area on the ground."""
    with connection.cursor() as cur:
        cur.execute(
            "SELECT ST_Area(ST_Intersection(x, y)::geography), ST_Area(x::geography), ST_Area(y::geography) "
            "FROM (SELECT ST_GeomFromEWKT(%s) AS x, ST_GeomFromEWKT(%s) AS y) s", [a.ewkt, b.ewkt])
        inter, ax, by_ = cur.fetchone()
    if not ax or not by_:
        return Decimal("0"), Decimal("0")
    return (Decimal(str(inter / ax)).quantize(Decimal("0.0001")),
            Decimal(str(inter / by_)).quantize(Decimal("0.0001")))


def _check_overlaps(alloc: Allocation, by):
    """US-REC-001 AC2: an allocation that overlaps another on the register is flagged for review."""
    found = []
    others = Allocation.objects.filter(country=alloc.country, geom__intersects=alloc.geom).exclude(
        pk=alloc.pk).exclude(status="revoked").exclude(pk=alloc.previous_id)
    for o in others:
        share, _ = _shares(alloc.geom, o.geom)
        if share < Decimal("0.01"):
            continue
        AllocationOverlap.objects.get_or_create(allocation=alloc, other=o, defaults={"share": share})
        found.append(o)
    if found and alloc.status == "captured":
        alloc.status_note = "Overlaps " + ", ".join(f"{o.authority.name} {o.reference}" for o in found)
        state.transition(alloc, "rec_allocation", "flagged", actor=by, reason=alloc.status_note,
                         extra_fields=["status_note"])
        for p in _staff_in(alloc.country, "CM"):
            _notify(p, "rec_overlap", f"Allocation {alloc.reference} overlaps another record. Review it.",
                    obj=alloc, link=f"/records/allocations/{alloc.pk}", needs_action=True)
    return found


@transaction.atomic
def capture_allocation(by, *, authority, reference, allottee_name, allocated_on, document_evidence, points=None,
                       geojson=None, coordinates=None, allottee_kind="person", allottee_phone="", locality="",
                       plot_number="", previous=None, extra_documents=()) -> Allocation:
    """US-REC-001 AC1: a paper record becomes a plot with boundary, allottee, date and scanned document."""
    from evidence.services import link
    from geo.services import parse_boundary

    _on(authority.country)
    if not (has_role(by, "CM", country=authority.country) or represents(by, authority)):
        raise Forbidden("Only a case manager or the authority's representative captures its records.")
    if document_evidence is None:
        raise Invalid("Attach the scanned record.", code="validation-error")
    if allocated_on > timezone.localdate():
        raise Invalid("The allocation date cannot be in the future.", code="validation-error")
    if Allocation.objects.filter(authority=authority, reference=reference.strip()).exists():
        raise StateConflict("This register entry is already captured.")
    if previous is not None and previous.authority_id != authority.pk:
        raise Invalid("The earlier allocation must be from the same authority.", code="validation-error")
    geom, _srid = parse_boundary(source="records_programme", points=points, geojson=geojson,
                                 coordinates=coordinates)
    allottee, _ = Allottee.objects.get_or_create(authority=authority, name=allottee_name.strip(),
                                                 defaults={"country": authority.country, "kind": allottee_kind,
                                                           "phone": allottee_phone or ""})
    a = Allocation.objects.create(country=authority.country, authority=authority, reference=reference.strip(),
                                  allottee=allottee, allocated_on=allocated_on, previous=previous, geom=geom,
                                  area_sqm=_area(geom), locality=locality or "", plot_number=plot_number or "",
                                  document_evidence=document_evidence, captured_by=by)
    link(document_evidence, "rec_allocation", a.pk, role="register_scan", by=by)
    for ev in extra_documents or ():
        link(ev, "rec_allocation", a.pk, role="supporting", by=by)
    _audit(by, "rec_allocation.captured", a, {"reference": a.reference, "area_sqm": a.area_sqm})
    _check_overlaps(a, by)
    return a


@transaction.atomic
def confirm_allocation(a: Allocation, by) -> Allocation:
    """US-REC-004 AC1: the authority's representative confirms; the record shows their name and the time."""
    _on(a.country)
    if not represents(by, a.authority):
        raise NotFound()  # AC2: another authority's record is not even visible
    if a.status not in ("captured",):
        raise StateConflict(f"This record is {a.status}. Only a captured record without open overlaps is confirmed.")
    a.confirmed_by, a.confirmed_name, a.confirmed_at = by, by.full_name, _now()
    return state.transition(a, "rec_allocation", "confirmed", actor=by,
                            extra_fields=["confirmed_by", "confirmed_name", "confirmed_at"])


@transaction.atomic
def dispute_allocation(a: Allocation, by, reason: str) -> Allocation:
    _on(a.country)
    if not (represents(by, a.authority) or has_role(by, "CM", "RV", country=a.country)):
        raise NotFound()
    if not (reason or "").strip():
        raise Invalid("Say what is wrong with the record.", code="validation-error")
    a.status_note = reason.strip()
    return state.transition(a, "rec_allocation", "disputed", actor=by, reason=reason, extra_fields=["status_note"])


@transaction.atomic
def correct_allocation(a: Allocation, by, *, note) -> Allocation:
    """A disputed or flagged record goes back to captured once staff have checked it."""
    if not has_role(by, "CM", "RV", country=a.country):
        raise Forbidden()
    if a.status == "flagged" and a.overlaps.filter(status="open").exists():
        raise StateConflict("Resolve the open overlaps first.")
    a.status_note = note or ""
    return state.transition(a, "rec_allocation", "captured", actor=by, reason=note, extra_fields=["status_note"])


@transaction.atomic
def resolve_overlap(o: AllocationOverlap, by, *, note) -> AllocationOverlap:
    if not has_role(by, "CM", "RV", country=o.allocation.country):
        raise Forbidden()
    if not (note or "").strip():
        raise Invalid("Record how the overlap was resolved.", code="validation-error")
    o.status, o.resolution_note, o.resolved_by = "resolved", note.strip(), by
    o.save(update_fields=["status", "resolution_note", "resolved_by"])
    a = o.allocation
    if a.status == "flagged" and not a.overlaps.filter(status="open").exists():
        state.transition(a, "rec_allocation", "captured", actor=by, reason="Overlaps resolved")
    return o


# =========================================================================== matching (FR-REC-002)

def chain_for(alloc: Allocation) -> list[dict]:
    """The chain of ownership the records show, oldest first, for section 9 (marked as from the records)."""
    chain, x, seen = [], alloc, set()
    while x is not None and x.pk not in seen:
        seen.add(x.pk)
        chain.append(x)
        x = x.previous
    out = []
    for a in reversed(chain):
        out.append({"from": a.previous.allottee.name if a.previous else a.authority.name, "to": a.allottee.name,
                    "date": a.allocated_on.isoformat(), "authority": a.authority.name,
                    "register_reference": a.reference, "document_sha256": a.document_evidence.sha256,
                    "confirmed_by_authority": a.status == "confirmed", "source": "records_programme"})
    return out


@transaction.atomic
def match_case(case) -> list[Match]:
    """US-REC-002 AC1, AC2: an exact overlap pre-fills the chain for the lawyer; a partial overlap is flagged for
    review with nothing pre-filled; no overlap does nothing."""
    if case is None or case.asset_id is None or not flags.enabled(FLAG, case.country):
        return []
    asset = case.asset
    bv = asset.current_boundary
    if bv is None:
        return []
    exact_at = _cfg(case.country, "records.match_exact_share", EXACT)
    near_at = _cfg(case.country, "records.match_near_share", NEAR)
    out = []
    for alloc in Allocation.objects.filter(country=case.country, geom__intersects=bv.geom).exclude(
            status__in=["revoked"]).select_related("authority", "allottee"):
        if Match.objects.filter(case=case, boundary=bv, allocation=alloc).exists():
            continue
        if alloc.later.exclude(status="revoked").exists():
            continue  # a later allocation of the same land carries the chain
        s_plot, s_rec = _shares(bv.geom, alloc.geom)
        if max(s_plot, s_rec) < near_at:
            continue
        exact = s_plot >= exact_at and s_rec >= exact_at and alloc.status in ("captured", "confirmed")
        m = Match.objects.create(country=case.country, case=case, asset=asset, boundary=bv, allocation=alloc,
                                 kind="exact" if exact else "near", share_of_plot=s_plot, share_of_record=s_rec,
                                 prefill=chain_for(alloc) if exact else [],
                                 status="proposed" if exact else "review")
        record(action="rec_match.found", entity="rec_match", entity_id=m.pk, country=case.country,
               data={"kind": m.kind, "case_id": str(case.pk), "allocation": alloc.reference})
        publish("record.matched", m.pk, {"match_id": m.pk, "case_id": case.pk, "asset_id": asset.pk,
                                         "allocation_id": alloc.pk, "authority_id": alloc.authority_id,
                                         "kind": m.kind, "country": case.country.code})
        for t in case.tasks.filter(owner_role="LW").exclude(assignee__isnull=True):
            _notify(t.assignee, "rec_match", f"Case {case.reference} matches a {alloc.authority.name} record "
                    + ("with the chain of ownership pre-filled. Confirm it." if exact else
                       "only in part. Review it; nothing is pre-filled."), obj=m,
                    link=f"/records/matches?asset_id={asset.pk}", needs_action=True)
        out.append(m)
    return out


def _lawyer_on(case, user) -> bool:
    return case.tasks.filter(owner_role="LW").filter(assignee=user).exists() or case.tasks.filter(
        owner_role="LW", second_assignee=user).exists()


@transaction.atomic
def confirm_match(m: Match, by, *, note="") -> Match:
    """The lawyer confirms the pre-filled chain; it is written into section 9 of the draft report, marked as from
    the records (TC-REC-002-01). A near match is confirmed only after the lawyer checks it by hand."""
    _on(m.country)
    if not (_lawyer_on(m.case, by) and has_role(by, "LW")):
        raise Forbidden("Only the lawyer on the case confirms a records match.")
    if m.status not in ("proposed", "review"):
        raise StateConflict("This match is already decided.")
    m.decided_by, m.decided_at, m.note = by, _now(), note or ""
    if m.kind == "exact":
        from reports.models import Report
        from reports.services import update_section

        report = Report.objects.filter(case=m.case, status="draft").order_by("-version").first()
        if report is not None:
            sec = report.sections.filter(number=9).first()
            findings = dict(sec.findings or {}) if sec else {}
            findings["chain_from_records"] = m.prefill
            findings["records_note"] = (f"Chain of ownership from the {m.allocation.authority.name} register "
                                        f"({m.allocation.reference}), confirmed by the lawyer.")
            update_section(report, 9, by, findings=findings)
            m.applied_to_report_id = report.pk
    state.transition(m, "rec_match", "confirmed", actor=by,
                     extra_fields=["decided_by", "decided_at", "note", "applied_to_report_id"])
    return m


@transaction.atomic
def reject_match(m: Match, by, *, note) -> Match:
    if not ((_lawyer_on(m.case, by) and has_role(by, "LW")) or has_role(by, "CM", country=m.country)):
        raise Forbidden()
    if m.status not in ("proposed", "review"):
        raise StateConflict("This match is already decided.")
    if not (note or "").strip():
        raise Invalid("Say why the record does not apply.", code="validation-error")
    m.decided_by, m.decided_at, m.note = by, _now(), note.strip()
    return state.transition(m, "rec_match", "rejected", actor=by, reason=note,
                            extra_fields=["decided_by", "decided_at", "note"])


# =========================================================================== revenue share (FR-REC-003)

@transaction.atomic
def compute_revenue_shares(by, *, country, period_start: date, period_end: date, authority=None):
    """US-REC-003 AC1: for each authority, the cases that used its records in the period (a confirmed match
    decided in the period), at the agreed share per case. A computed (not yet approved) share is recomputed."""
    _on(country)
    if not has_role(by, "AD", country=country):
        raise Forbidden("Only an administrator computes revenue shares.")
    if period_end < period_start:
        raise Invalid("The period ends before it starts.", code="validation-error")
    auths = [authority] if authority else list(Authority.objects.filter(country=country))
    out = []
    for a in auths:
        existing = RevenueShare.objects.filter(authority=a, period_start=period_start, period_end=period_end).first()
        if existing and existing.status != "computed":
            out.append(existing)
            continue
        matches = Match.objects.filter(allocation__authority=a, status__in=USED, decided_at__date__gte=period_start,
                                       decided_at__date__lte=period_end).exclude(
            pk__in=RevenueShareItem.objects.exclude(share=existing).values("match_id") if existing else
            RevenueShareItem.objects.values("match_id"))
        per_case = {}
        for m in matches.order_by("decided_at"):
            per_case.setdefault(m.case_id, m)  # one share per case, even if it used several records
        if existing:
            existing.items.all().delete()
            share = existing
        else:
            share = RevenueShare(country=country, authority=a, period_start=period_start, period_end=period_end,
                                 computed_by=by, currency=a.share_currency, case_count=0, amount=0)
        share.case_count = len(per_case)
        share.amount = q(a.share_per_case * len(per_case))
        share.currency, share.computed_by = a.share_currency, by
        share.save()
        for case_id, m in per_case.items():
            RevenueShareItem.objects.create(share=share, match=m, case_id=case_id, amount=a.share_per_case)
        _audit(by, "rec_revenue_share.computed", share, {"cases": share.case_count, "amount": share.amount})
        out.append(share)
    return out


@transaction.atomic
def approve_share(s: RevenueShare, by) -> RevenueShare:
    if not has_role(by, "AD", country=s.country):
        raise Forbidden()
    if by.pk == s.computed_by_id:
        raise SameApprover("A second administrator approves the share.")
    s.approved_by = by
    return state.transition(s, "rec_revenue_share", "approved", actor=by, extra_fields=["approved_by"])


@transaction.atomic
def mark_share_paid(s: RevenueShare, by, *, reference) -> RevenueShare:
    if not has_role(by, "AD", country=s.country):
        raise Forbidden()
    if not (reference or "").strip():
        raise Invalid("Give the payment reference.", code="validation-error")
    s.paid_reference = reference.strip()
    s = state.transition(s, "rec_revenue_share", "paid", actor=by, extra_fields=["paid_reference"])
    for r in s.authority.representatives.filter(active=True):
        _notify(r.person, "rec_share_paid", f"Tenmina paid {s.currency} {s.amount:,.2f} for "
                f"{s.case_count} cases that used your records.", obj=s, link="/records/revenue-shares")
    return s
