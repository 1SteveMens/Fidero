"""PMG event subscribers and registrations. Handlers are idempotent and never raise a domain error back into
the producer's transaction.

Consumes: case.status_changed, statement.line_imported, submission.received, escrow.funded, release.confirmed,
release.withdrawn, release.rejected, release.rejected_by_bank, payee.suspended.
Registers: the escrow subject check and label for `repair`, client home items (owner and tenant), the field
inbox (property inspections), evidence access for managed_property, tenancy, repair and property_inspection,
data protection open matters and exporter.
"""
import logging

from django.db import transaction

from core.errors import DomainError
from core.events import subscribe

log = logging.getLogger(__name__)


def _safe(fn, *args, **kw):
    try:
        with transaction.atomic():
            return fn(*args, **kw)
    except DomainError as exc:
        log.info("propertymgmt handler %s: %s", getattr(fn, "__name__", fn), exc.detail)
        return None


@subscribe("case.status_changed")
def on_case_status(ev):
    p = ev.payload
    if p.get("entity") != "case" or p.get("product_line") != "property_onboarding" or p.get("to") != "completed":
        return
    from . import services

    _safe(services.on_onboarding_case, p.get("case_id") or p.get("id"), p.get("outcome") or "", p.get("reason", ""))


@subscribe("statement.line_imported")
def on_statement_line(ev):
    """pmg.match_rent on import: only lines tagged with an active mandate's statement reference are read."""
    from escrow.models import StatementLine

    from .models import StatementMandate
    from . import services

    p = ev.payload
    ref = p.get("virtual_account_ref") or ""
    m = StatementMandate.objects.filter(statement_ref=ref).select_related("property").first() if ref else None
    if m is None:
        return
    line = StatementLine.objects.filter(pk=p.get("line_id")).first()
    if line is None:
        return
    if services.live_mandate(m.property, line.booked_on) is None or m.status != "active":
        log.info("rent line %s ignored: no active mandate on %s", line.pk, line.booked_on)
        return
    _safe(services.match_line, line, m)


@subscribe("submission.received")
def on_submission(ev):
    if ev.payload.get("subject_type") != "property_inspection":
        return
    from . import services

    services.on_field_submission(ev.payload)


@subscribe("escrow.funded")
def on_funded(ev):
    if ev.payload.get("kind") != "repair":
        return
    from . import services

    _safe(services.on_escrow_funded, ev.payload.get("escrow_id"))


@subscribe("release.confirmed")
def on_release_confirmed(ev):
    if ev.payload.get("subject_type") != "repair":
        return
    from . import services

    _safe(services.on_release_confirmed, ev.payload)


@subscribe("release.withdrawn", "release.rejected", "release.rejected_by_bank")
def on_release_closed(ev):
    if ev.payload.get("subject_type") != "repair":
        return
    from . import services

    _safe(services.on_release_closed, ev.payload)


@subscribe("payee.suspended")
def on_payee_suspended(ev):
    """A suspended contractor payee cannot be chosen: tell the case manager about open quotes."""
    from .models import RepairQuote
    from . import services

    for qt in RepairQuote.objects.filter(payee_id=ev.payload.get("payee_id"), status="received") \
            .select_related("repair", "repair__property"):
        services._alert_staff(qt.country, "pmg_quote_payee_suspended",
                              f"The payee on a quote for '{qt.repair.title}' was suspended. Withdraw the quote or "
                              "wait for it to be reinstated.", obj=qt.repair, prop=qt.repair.property)


# --------------------------------------------------------------------------- registrations

def _register():
    from accounts import home
    from dataprotection import registry as dpr
    from escrow import registry as esc_registry
    from evidence import access
    from mobile import inbox

    from . import services
    from .models import Inspection, ManagedProperty, Repair, Tenancy

    esc_registry.register_subject_check("repair", services.repair_release_check)
    esc_registry.subject_label("repair", services.repair_label)

    @home.register
    def pmg_home(person):
        out = []
        for prop in ManagedProperty.objects.filter(owner=person).exclude(status="ended").select_related(
                "rent_account"):
            blockers = services.activation_blockers(prop) if prop.status == "onboarding" else []
            needs = prop.rent_account_id is None or (prop.status == "managed" and services.live_mandate(prop) is None
                                                     and not prop.mandates.filter(status="signed").exists())
            if prop.status == "onboarding":
                text = blockers[0]["message"] if blockers else "Getting ready for management."
            elif needs:
                text = "Sign the statement mandate so we can see your rent arrive."
            else:
                late = prop.tenancies.filter(status="active", periods__status="late").exists()
                text = "Rent is late. We alerted the tenant." if late else "Under management."
            out.append(home.item(kind="managed_property", id=prop.pk, title=prop.title, status=prop.status,
                                 status_text=text, next_date=prop.next_inspection_due_on, needs_action=needs,
                                 link=services.property_link(prop), line="pmg"))
        for r in Repair.objects.filter(property__owner=person, status__in=services.OPEN_REPAIR):
            out.append(home.item(kind="repair", id=r.pk, title=f"Repair: {r.title}", status=r.status,
                                 status_text={"quotes_ready": "Choose a quote.",
                                              "approved": "Pay the repair amount to the bank."}.get(
                                     r.status, r.status.replace("_", " ").capitalize() + "."),
                                 needs_action=r.status in ("quotes_ready", "approved"), link=f"/repairs/{r.pk}",
                                 line="pmg"))
        for t in Tenancy.objects.filter(tenant=person, status="active").select_related("property"):
            nxt = t.periods.filter(status__in=["due", "late", "partial"]).order_by("due_on").first()
            out.append(home.item(kind="tenancy", id=t.pk, title=f"Tenancy: {t.property.title}", status=t.status,
                                 status_text=("Rent is late. Pay the owner's own account." if nxt and nxt.status ==
                                              "late" else "Pay rent to the owner's own account only."),
                                 next_date=nxt.due_on if nxt else None, link=f"/tenancies/{t.pk}", line="pmg",
                                 amount={"amount": f"{t.rent_amount:.2f}", "currency": t.rent_currency}))
        return out

    @inbox.register
    def pmg_inspections(person):
        if not person.has_tenmina_role("IN"):
            return
        for insp in Inspection.objects.filter(inspector=person, status="assigned").select_related(
                "property", "property__asset", "repair", "country"):
            asset = insp.property.asset
            point = (asset.location.y, asset.location.x) if asset.location is not None else None
            if insp.kind == "repair":
                checklist = [{"key": "work_complete", "label": "The work quoted is complete"},
                             {"key": "quality", "label": "The work is of acceptable quality"},
                             {"key": "site_clean", "label": "The site is clean and safe"}]
                evidence = [{"key": "work_photo", "label": "Photo of the finished work", "media": "photo",
                             "required": True}]
                title = f"Repair inspection: {insp.repair.title}"
            else:
                checklist = [{"key": k, "label": label} for k, label in (
                    ("structure", "Walls, floors and structure"), ("roof", "Roof and ceilings"),
                    ("plumbing", "Plumbing and water"), ("electrical", "Electrical"),
                    ("doors_windows", "Doors, windows and locks"))]
                evidence = [{"key": "room_front", "label": "Front of the house", "media": "photo", "required": True},
                            {"key": "room_living", "label": "Living room", "media": "photo", "required": True},
                            {"key": "room_kitchen", "label": "Kitchen", "media": "photo", "required": False},
                            {"key": "condition_rating", "label": "Overall condition: good, fair or poor",
                             "media": "value", "required": False}]
                title = f"{insp.kind.capitalize()} inspection: {insp.property.title}"
            yield inbox.InboxItem(subject_type="property_inspection", subject_id=str(insp.pk), title=title,
                                  kind="inspection", country=insp.country, address=asset.address or asset.locality,
                                  point=point, radius_m=100 if point else None, required_evidence=evidence,
                                  checklist=checklist, due_at=None, updated_at=insp.updated_at,
                                  project_key=f"property:{insp.property_id}",
                                  details={"kind": insp.kind, "scheduled_for": insp.scheduled_for.isoformat()})

    def _prop(sid):
        return ManagedProperty.objects.filter(pk=sid).first()

    access.register("managed_property",
                    can_view=lambda u, sid: (lambda p: bool(p) and services.can_view_property(u, p))(_prop(sid)),
                    can_attach=lambda u, sid: (lambda p: bool(p) and services.can_view_property(u, p))(_prop(sid)),
                    country=lambda sid: getattr(_prop(sid), "country", None),
                    owner=lambda sid: ("managed_property", sid))

    # FR-PMG-001: an owner stores ownership documents before the property exists, so they can register it.
    # The subject is the owner themself; only they (and staff) see or add these files.
    def _owner_country(sid):
        from accounts.models import Person

        return getattr(Person.objects.filter(pk=sid).first(), "home_country", None)

    access.register("pmg_owner_document",
                    can_view=lambda u, sid: str(u.pk) == str(sid) or services.is_staff(u, _owner_country(sid)),
                    can_attach=lambda u, sid: str(u.pk) == str(sid),
                    country=_owner_country)

    def _ten(sid):
        return Tenancy.objects.filter(pk=sid).select_related("property").first()

    access.register("tenancy",
                    can_view=lambda u, sid: (lambda t: bool(t) and services.can_view_tenancy(u, t))(_ten(sid)),
                    can_attach=lambda u, sid: (lambda t: bool(t) and services.is_staff(u, t.country))(_ten(sid)),
                    country=lambda sid: getattr(_ten(sid), "country", None),
                    owner=lambda sid: ("managed_property", getattr(_ten(sid), "property_id", None)))

    def _rep(sid):
        return Repair.objects.filter(pk=sid).select_related("property", "approved_quote").first()

    access.register("repair",
                    can_view=lambda u, sid: (lambda r: bool(r) and services.can_view_repair(u, r))(_rep(sid)),
                    can_attach=lambda u, sid: (lambda r: bool(r) and services.can_view_repair(u, r))(_rep(sid)),
                    country=lambda sid: getattr(_rep(sid), "country", None),
                    owner=lambda sid: ("managed_property", getattr(_rep(sid), "property_id", None)))

    def _insp(sid):
        return Inspection.objects.filter(pk=sid).select_related("property").first()

    access.register("property_inspection",
                    can_view=lambda u, sid: (lambda i: bool(i) and services.can_view_inspection(u, i))(_insp(sid)),
                    can_attach=lambda u, sid: (lambda i: bool(i) and (i.inspector_id == u.pk or services.is_staff(
                        u, i.country)))(_insp(sid)),
                    country=lambda sid: getattr(_insp(sid), "country", None),
                    owner=lambda sid: ("managed_property", getattr(_insp(sid), "property_id", None)))

    @dpr.open_matters
    def pmg_open_matters(person):
        out = []
        for r in Repair.objects.filter(property__owner=person, status__in=["approved", "funded", "in_progress",
                                                                          "inspected", "instructed"]):
            out.append({"kind": "repair", "id": str(r.pk), "title": f"Repair: {r.title}",
                        "reason": "Repair money is held at the bank."})
        for t in Tenancy.objects.filter(property__owner=person, status="active"):
            out.append({"kind": "tenancy", "id": str(t.pk), "title": f"Tenancy of {t.property.title}",
                        "reason": "A tenancy is active on your managed property."})
        return out

    @dpr.exporter("property_management")
    def pmg_export(person):
        props = [{"id": str(p.pk), "title": p.title, "status": p.status, "registered": p.created_at.isoformat(),
                  "rent_account_last4": p.rent_account.last4 if p.rent_account_id else None}
                 for p in ManagedProperty.objects.filter(owner=person)]
        tenancies = [{"id": str(t.pk), "property": t.property.title, "rent": f"{t.rent_amount:.2f}",
                      "currency": t.rent_currency, "starts_on": t.starts_on.isoformat(), "status": t.status,
                      "periods": [{"due_on": p.due_on.isoformat(), "status": p.status} for p in t.periods.all()]}
                     for t in Tenancy.objects.filter(tenant=person)]
        repairs = [{"id": str(r.pk), "title": r.title, "status": r.status, "reported": r.created_at.isoformat()}
                   for r in Repair.objects.filter(reported_by=person)]
        return {"properties": props, "tenancies_as_tenant": tenancies, "repairs_reported": repairs}

    @dpr.retention("tenancy")
    def ended_tenancies(scope, cutoff):
        qs = scope.filter(Tenancy.objects.filter(status__in=["ended", "terminated"], ended_at__lt=cutoff))
        for t in qs:
            yield dpr.Candidate("tenancy", t.pk, apply=lambda t=t: Tenancy.objects.filter(pk=t.pk).update(
                tenant_reference="[removed]"), related=[("managed_property", t.property_id)],
                label=f"Tenancy of {t.property.title}")


_register()
